"""
Cordis Fiber lifecycle, effects, and composite epoch dependency engine
matching reference/vendor/cordis/src/fiber.ts
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dsh.cordis.schema import Schema, ValidationError
from dsh.cordis.utils import DisposableList, build_outer_stack, compose_error, symbols


class FiberState:
    PENDING = 0
    LOADING = 1
    ACTIVE = 2
    FAILED = 3
    DISPOSED = 4
    UNLOADING = 5


class CordisError(Exception):
    """Framework error with a stable error code."""
    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code
        super().__init__(message or code)


def resolve_config(plugin: Any, config: Any) -> Any:
    """
    Validate and normalize config for a plugin runtime before it starts matching TS resolveConfig.
    """
    if config is None and isinstance(getattr(plugin, "config", None), dict):
        config = dict(getattr(plugin, "config", {}))
    elif config is None:
        config = {}

    schema = getattr(plugin, "schema", None) or getattr(plugin, "Config", None)
    if not schema:
        return config

    if isinstance(schema, Schema):
        res = schema.validate(config)
        if "issues" in res and res["issues"]:
            raise ValidationError(res["issues"])
        return res.get("value", config)
    elif hasattr(schema, "validate") and callable(schema.validate):
        res = schema.validate(config)
        if isinstance(res, dict) and "issues" in res and res["issues"]:
            raise ValidationError(res["issues"])
        return res.get("value", config) if isinstance(res, dict) and "value" in res else res

    return config


class EffectMeta:
    """Tree node used to expose nested effect labels for diagnostics."""
    def __init__(self, label: str, children: Optional[List["EffectMeta"]] = None):
        self.label = label
        self.children: List["EffectMeta"] = children or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "children": [c.to_dict() for c in self.children]
        }


INACTIVE_EPOCH = "__INACTIVE__"


class Fiber:
    """
    Runtime instance of one plugin application matching reference/vendor/cordis/src/fiber.ts.
    Tracks dependency state, composite epoch calculations, validated config, lifecycle effects, and cleanup.
    """

    _uid_counter = 0

    def __init__(
        self,
        parent_ctx: Any,
        plugin: Any,
        config: Any = None,
        runtime: Any = None,
        inject: Optional[Dict[str, Any]] = None,
        get_outer_stack: Optional[Callable[[], List[str]]] = None,
    ):
        self.parent = parent_ctx
        self.plugin = plugin
        self.runtime = runtime
        self._config = config
        self.config = config
        self.entry: Optional[Any] = None
        self.store: Optional[Dict[str, Any]] = {}
        self._store: Dict[str, Any] = {}
        self.inertia: Optional[asyncio.Future] = None
        self.epoch: str = INACTIVE_EPOCH
        self._error: Optional[Exception] = None
        self.get_outer_stack = get_outer_stack or build_outer_stack()

        # Dependency map (service_name -> intercept_config)
        if inject is not None:
            self.inject = inject
        elif hasattr(plugin, "inject"):
            raw_inject = getattr(plugin, "inject", [])
            if isinstance(raw_inject, (list, tuple)):
                self.inject = {k: None for k in raw_inject}
            elif isinstance(raw_inject, dict):
                self.inject = dict(raw_inject)
            else:
                self.inject = {}
        else:
            self.inject = {}

        self._disposables: DisposableList[Callable[[], Any]] = DisposableList()
        self._effect_metas: Dict[Any, EffectMeta] = {}
        self._hooks: Dict[str, DisposableList[Any]] = {}

        if runtime is not None:
            # Plugin Fiber
            if hasattr(parent_ctx, "registry"):
                self.uid = parent_ctx.registry.counter
            else:
                Fiber._uid_counter += 1
                self.uid = Fiber._uid_counter
            self.ctx = parent_ctx.extend({"fiber": self}) if parent_ctx else None
            self.state = FiberState.PENDING
        else:
            # Root Fiber (runtime is None)
            self.uid = 0
            self.ctx = parent_ctx
            self.state = FiberState.ACTIVE
            self.epoch = ""

    @property
    def name(self) -> str:
        if self.plugin:
            if hasattr(self.plugin, "name") and self.plugin.name:
                return self.plugin.name
            if hasattr(self.plugin, "id") and self.plugin.id:
                return self.plugin.id
            if isinstance(self.plugin, type):
                return self.plugin.__name__
            return self.plugin.__class__.__name__
        return "root"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in ("uid", "ctx", "config", "_config", "state", "dispose", "store", "inertia", "epoch", "parent", "plugin", "runtime", "inject"):
            raise AttributeError(f"'Fiber' object has no attribute '{name}'")
        if self.plugin is not None and hasattr(self.plugin, name):
            return getattr(self.plugin, name)
        raise AttributeError(f"'Fiber' object has no attribute '{name}'")

    def __await__(self):
        return self.await_settled().__await__()

    def assert_active(self) -> None:
        if self.uid is None or self.state in (FiberState.DISPOSED, FiberState.UNLOADING, FiberState.FAILED):
            if self._error is not None:
                raise self._error
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

    def _resolve_config(self, config: Any) -> Any:
        """Resolve raw plugin config through internal/config waterfall matching TS."""
        if self.ctx and hasattr(self.ctx, "waterfall_sync"):
            config = self.ctx.waterfall_sync("internal/config", config, caller_ctx=self.ctx)
        return resolve_config(self.plugin, config)

    def effect(self, execute_or_disposer: Any, label: str = "anonymous") -> Callable[[], Any]:
        """
        Register a cleanup-aware effect on this fiber.
        Supports functions, generators, async generators, and coroutines.
        Handles setup rollback on failure and barrier synchronization.
        """
        self.assert_active()
        if self.state == FiberState.UNLOADING:
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

        disposables: List[Callable[[], Any]] = []
        meta = EffectMeta(label=label)
        in_flight_cleanup: Optional[asyncio.Task] = None
        setup_task: Optional[asyncio.Task] = None
        setup_barrier_future: Optional[asyncio.Future] = None
        executing = True
        setup_failed = False
        disposed = False

        def collect_disposer(disp: Any) -> None:
            if callable(disp):
                disposables.append(disp)

        def rollback_sync() -> None:
            if in_flight_cleanup is not None:
                return
            while disposables:
                disp = disposables.pop()
                self._disposables.delete(disp)
                try:
                    res = disp()
                    if inspect.isawaitable(res):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(res)
                        except RuntimeError:
                            pass
                except Exception as e:
                    if self.ctx and hasattr(self.ctx, "logger"):
                        self.ctx.logger("fiber").warn("Exception in effect rollback '%s': %s", label, e)

        def wait_for_setup() -> Optional[asyncio.Future]:
            nonlocal setup_barrier_future
            if setup_barrier_future is None:
                try:
                    loop = asyncio.get_running_loop()
                    setup_barrier_future = loop.create_future()
                except RuntimeError:
                    pass
            return setup_barrier_future

        def cancel_effect() -> Any:
            nonlocal disposed, in_flight_cleanup
            if disposed:
                return in_flight_cleanup
            disposed = True
            self._effect_metas.pop(cancel_effect, None)

            if executing:
                barrier = wait_for_setup()
                async def _dispose_after_barrier():
                    cleanup_fn = None
                    if barrier is not None:
                        try:
                            cleanup_fn = await barrier
                        except Exception:
                            pass
                    if callable(cleanup_fn):
                        try:
                            r = cleanup_fn()
                            if inspect.isawaitable(r):
                                await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").warn("Exception in disposer '%s': %s", label, err)
                    while disposables:
                        disp = disposables.pop()
                        self._disposables.delete(disp)
                        try:
                            r = disp()
                            if inspect.isawaitable(r):
                                await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").warn("Exception in disposer '%s': %s", label, err)

                try:
                    loop = asyncio.get_running_loop()
                    in_flight_cleanup = loop.create_task(_dispose_after_barrier())
                    return in_flight_cleanup
                except RuntimeError:
                    return None

            async_disposers = []
            while disposables:
                disp = disposables.pop()
                self._disposables.delete(disp)
                try:
                    r = disp()
                    if inspect.isawaitable(r):
                        async_disposers.append(r)
                except Exception as e:
                    if self.ctx and hasattr(self.ctx, "logger"):
                        self.ctx.logger("fiber").warn("Exception running disposer '%s': %s", label, e)
                    else:
                        sys.stderr.write(f"[Cordis Fiber Error] Exception running disposer '{label}': {e}\n")

            if async_disposers or (setup_task and not setup_task.done()):
                async def _run_cleanup():
                    cleanup_fn = None
                    if setup_task and not setup_task.done():
                        try:
                            cleanup_fn = await setup_task
                        except Exception:
                            pass
                    if callable(cleanup_fn):
                        try:
                            r = cleanup_fn()
                            if inspect.isawaitable(r):
                                await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").warn("Exception in async disposer '%s': %s", label, err)
                    for r in async_disposers:
                        try:
                            await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").warn("Exception in async disposer '%s': %s", label, err)

                try:
                    loop = asyncio.get_running_loop()
                    in_flight_cleanup = loop.create_task(_run_cleanup())
                    return in_flight_cleanup
                except RuntimeError:
                    for r in async_disposers:
                        try:
                            asyncio.run(r)
                        except Exception:
                            pass
                    return None
            return None

        self._effect_metas[cancel_effect] = meta
        self._disposables.push(cancel_effect)

        if callable(execute_or_disposer):
            fn_name = getattr(execute_or_disposer, "__name__", "")
            if fn_name in ("disposer", "cancel_effect", "teardown", "cleanup", "unregister", "remove") or "on(" in label or "once(" in label:
                collect_disposer(execute_or_disposer)
            else:
                try:
                    res = execute_or_disposer()
                    if callable(res):
                        collect_disposer(res)
                        if setup_barrier_future and not setup_barrier_future.done():
                            setup_barrier_future.set_result(res)
                    elif inspect.isawaitable(res):
                        async def _await_async_setup(res=res):
                            try:
                                cleanup = await res
                                if callable(cleanup):
                                    collect_disposer(cleanup)
                                if setup_barrier_future and not setup_barrier_future.done():
                                    setup_barrier_future.set_result(cleanup)
                                return cleanup
                            except Exception as async_err:
                                rollback_sync()
                                if setup_barrier_future and not setup_barrier_future.done():
                                    setup_barrier_future.set_exception(async_err)
                                if self.ctx and hasattr(self.ctx, "logger"):
                                    self.ctx.logger("fiber").error("Exception in async effect '%s': %s", label, async_err)
                                raise async_err
                        try:
                            loop = asyncio.get_running_loop()
                            setup_task = loop.create_task(_await_async_setup())
                        except RuntimeError:
                            pass
                    elif res is None or isinstance(res, (bool, int, float, str)):
                        if setup_barrier_future and not setup_barrier_future.done():
                            setup_barrier_future.set_result(None)
                    elif inspect.isgenerator(res):
                        try:
                            for item in res:
                                if callable(item):
                                    collect_disposer(item)
                            if setup_barrier_future and not setup_barrier_future.done():
                                setup_barrier_future.set_result(None)
                        except Exception as gen_err:
                            rollback_sync()
                            if setup_barrier_future and not setup_barrier_future.done():
                                setup_barrier_future.set_exception(gen_err)
                            raise gen_err
                    elif inspect.isasyncgen(res):
                        async def _consume_async_gen():
                            try:
                                async for item in res:
                                    if callable(item):
                                        collect_disposer(item)
                                if setup_barrier_future and not setup_barrier_future.done():
                                    setup_barrier_future.set_result(None)
                            except Exception as asyncgen_err:
                                rollback_sync()
                                if setup_barrier_future and not setup_barrier_future.done():
                                    setup_barrier_future.set_exception(asyncgen_err)
                                if self.ctx and hasattr(self.ctx, "logger"):
                                    self.ctx.logger("fiber").error("Exception consuming async generator '%s': %s", label, asyncgen_err)
                        try:
                            loop = asyncio.get_running_loop()
                            setup_task = loop.create_task(_consume_async_gen())
                        except RuntimeError:
                            pass
                except Exception as e:
                    executing = False
                    setup_failed = True
                    self._effect_metas.pop(cancel_effect, None)
                    self._disposables.delete(cancel_effect)
                    if setup_barrier_future and not setup_barrier_future.done():
                        setup_barrier_future.set_exception(e)
                    rollback_sync()
                    if self.ctx and hasattr(self.ctx, "logger"):
                        self.ctx.logger("fiber").error("Exception in effect execution '%s': %s", label, e)
                    raise e
        executing = False

        return cancel_effect

    def get_effects(self) -> List[Dict[str, Any]]:
        """Return metadata for currently registered effects."""
        return [meta.to_dict() for meta in self._effect_metas.values()]

    @property
    def error(self) -> Optional[Exception]:
        return self._error

    def set_state(self, new_state: int) -> None:
        """Update fiber state with notifications."""
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/status", self, old_state)

        # Notify reflect store if transitioning between ACTIVE and non-ACTIVE states
        if (old_state == FiberState.ACTIVE or self.state == FiberState.ACTIVE) and self.ctx and hasattr(self.ctx, "reflect"):
            provided_names = []
            for name, impl in list(self.ctx.reflect.store.items()):
                if getattr(impl, "fiber", None) is self:
                    provided_names.append(getattr(impl, "name", str(name)))
            if provided_names:
                self.ctx.reflect.notify(provided_names)

    def _checkImpl(self, name: str) -> None:
        """
        Verify implementation availability for a required dependency service.
        Matches 1:1 TS Fiber._checkImpl.
        """
        if not self.ctx or not hasattr(self.ctx, "reflect"):
            return
        impl = self.ctx.reflect._get_impl(self.ctx, name, strict=True)
        if not impl:
            self._store.pop(name, None)
            return
        try:
            if impl.check and callable(impl.check) and not impl.check():
                self._store.pop(name, None)
                return
        except Exception as e:
            if self.ctx and hasattr(self.ctx, "logger"):
                self.ctx.logger("fiber").warn("Exception checking impl availability for '%s': %s", name, e)
            else:
                sys.stderr.write(f"[Cordis Fiber Error] Exception checking impl availability for '{name}': {e}\n")
            self._store.pop(name, None)
            return
        self._store[name] = impl

    def _refresh(self) -> None:
        """
        1:1 Composite Epoch calculation matching TS Cordis Fiber._refresh.
        Computes composite epoch hash of all active dependencies (:uid1:uid2)
        and triggers state reload if changed.
        """
        epoch = ""
        for name, config in self.inject.items():
            is_required = True
            if isinstance(config, dict):
                is_required = config.get("required", True)
            elif isinstance(config, bool):
                is_required = config

            impl = self._store.get(name)
            if not impl:
                if is_required:
                    epoch = INACTIVE_EPOCH
                    break
                continue

            fib = getattr(impl, "fiber", None)
            if fib is not None and fib.state != FiberState.ACTIVE and getattr(fib, "uid", None) not in (0, None):
                if is_required:
                    epoch = INACTIVE_EPOCH
                    break
                continue

            epoch += f":{getattr(fib, 'uid', 0)}"

        self.set_epoch(epoch)

    def set_epoch(self, epoch: str) -> None:
        """Update fiber epoch and trigger reload or unload transition if needed."""
        old_epoch = self.epoch
        if epoch == old_epoch:
            return
        self.epoch = epoch
        if self.inertia is not None and not self.inertia.done():
            return

        if epoch != INACTIVE_EPOCH and old_epoch == INACTIVE_EPOCH:
            self.set_state(FiberState.LOADING)
            self._reload()
        elif epoch == INACTIVE_EPOCH and old_epoch != INACTIVE_EPOCH:
            self.set_state(FiberState.UNLOADING)
            self._unload()
        elif epoch != INACTIVE_EPOCH and old_epoch != INACTIVE_EPOCH:
            # Composite epoch changed due to upstream dependency restart/replacement -> reload!
            self.set_state(FiberState.UNLOADING)
            self._unload()

    def _reload(self) -> None:
        """Execute plugin apply and transition to ACTIVE on success."""
        epoch = self.epoch
        try:
            self.store = dict(self._store)
            self.config = self._resolve_config(self._config)
            if hasattr(self.plugin, "config"):
                self.plugin.config = self.config
            if hasattr(self.plugin, "ctx"):
                self.plugin.ctx = self.ctx

            # 1:1 Execute init hooks and symbols.init matching TS Fiber execute
            init_hooks = getattr(self.plugin, symbols.initHooks, None) or getattr(self.plugin, "_init_hooks", [])
            for hook in list(init_hooks):
                if callable(hook):
                    hook()

            if hasattr(self.plugin, symbols.init) and callable(getattr(self.plugin, symbols.init)):
                init_res = getattr(self.plugin, symbols.init)()
                if inspect.isawaitable(init_res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(init_res)
                    except RuntimeError:
                        pass

            if hasattr(self.plugin, "teardown") and callable(self.plugin.teardown):
                self.effect(self.plugin.teardown, label=f"teardown({self.name})")

            res = None
            if hasattr(self.plugin, "apply") and callable(self.plugin.apply):
                res = self.plugin.apply(self.ctx)
            elif callable(self.plugin):
                res = self.plugin(self.ctx, self.config)

            if inspect.isawaitable(res):
                async def _async_wait_res():
                    try:
                        await res
                        self._error = None
                        self.set_state(FiberState.ACTIVE)
                    except Exception as e:
                        self._error = e
                        self.epoch = INACTIVE_EPOCH
                        self.set_state(FiberState.FAILED)
                try:
                    loop = asyncio.get_running_loop()
                    self.inertia = loop.create_task(_async_wait_res())
                    return
                except RuntimeError:
                    asyncio.run(res)

            self._error = None
            self.set_state(FiberState.ACTIVE)
        except Exception as e:
            self._error = e
            self.epoch = INACTIVE_EPOCH
            self.set_state(FiberState.FAILED)

        if self.epoch != epoch:
            self.set_state(FiberState.UNLOADING)
            self._unload()

    def _unload(self) -> None:
        """Execute all disposers in reverse order and transition state."""
        disposers = self._disposables.clear()
        async_disposers = []
        for disposer in disposers:
            try:
                res = disposer()
                if inspect.isawaitable(res):
                    async_disposers.append(res)
            except Exception as e:
                if self.ctx and hasattr(self.ctx, "logger"):
                    self.ctx.logger("fiber").warn("Exception during unload for '%s': %s", self.name, e)
                else:
                    sys.stderr.write(f"[Cordis Fiber Error] Exception during unload for '{self.name}': {e}\n")

        if async_disposers:
            async def _run_async_disposers():
                for r in async_disposers:
                    try:
                        await r
                    except Exception as e:
                        if self.ctx and hasattr(self.ctx, "logger"):
                            self.ctx.logger("fiber").warn("Exception during async unload for '%s': %s", self.name, e)
                self.store = None
                if self.epoch == INACTIVE_EPOCH:
                    final_state = FiberState.FAILED if self._error is not None else (FiberState.PENDING if self.uid is not None else FiberState.DISPOSED)
                    self.set_state(final_state)
                    self.inertia = None
                else:
                    self.set_state(FiberState.LOADING)
                    self._reload()

            try:
                loop = asyncio.get_running_loop()
                self.inertia = loop.create_task(_run_async_disposers())
                return
            except RuntimeError:
                for r in async_disposers:
                    try:
                        asyncio.run(r)
                    except Exception:
                        pass

        self.store = None
        if self.epoch == INACTIVE_EPOCH:
            final_state = FiberState.FAILED if self._error is not None else (FiberState.PENDING if self.uid is not None else FiberState.DISPOSED)
            self.set_state(final_state)
        else:
            self.set_state(FiberState.LOADING)
            self._reload()

    async def dispose(self) -> None:
        """Dispose this fiber and execute disposers in strict reverse order matching TS fiber.dispose."""
        if self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
            return
        self.uid = None
        self.set_epoch(INACTIVE_EPOCH)
        if not self.inertia or self.inertia.done():
            self.set_state(FiberState.UNLOADING)
            self._unload()
        while self.inertia is not None and not self.inertia.done():
            await self.inertia

        self.set_state(FiberState.DISPOSED)
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/plugin", self)

    def update(self, config: Any, no_save: bool = False) -> Any:
        """
        Validate and apply new config, then restart the plugin via internal/update waterfall.
        """
        self.assert_active()
        self._config = config
        if hasattr(self.ctx, "waterfall_sync"):
            return self.ctx.waterfall_sync("internal/update", config, no_save, lambda cfg=config: self.restart(cfg))
        return self.restart(config)

    def restart(self, new_config: Optional[Any] = None) -> Any:
        """Dispose and immediately reload this plugin with current or new config matching TS fiber.restart()."""
        self.assert_active()
        if new_config is not None:
            self._config = new_config
        self.set_epoch(INACTIVE_EPOCH)
        for name in list(self.inject.keys()):
            self._checkImpl(name)
        self._refresh()

        async def _wait_settled():
            while self.inertia is not None and not self.inertia.done():
                await self.inertia
            if self._error:
                raise self._error
            return None

        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(_wait_settled())
        except RuntimeError:
            return None

    async def await_settled(self) -> "Fiber":
        """Wait for current lifecycle transitions to settle."""
        while self.inertia is not None and not self.inertia.done():
            await self.inertia
        if self._error:
            raise self._error
        return self

    def __repr__(self) -> str:
        return f"<Fiber {self.name} uid={self.uid} state={self.state} epoch={self.epoch}>"
