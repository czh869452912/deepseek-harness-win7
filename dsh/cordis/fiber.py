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


CODE_MESSAGES = {
    "INACTIVE_EFFECT": "cannot create effect on inactive context"
}


class CordisError(Exception):
    """Framework error with a stable error code."""
    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code
        super().__init__(message or CODE_MESSAGES.get(code, code))


def resolve_config(plugin: Any, config: Any, runtime: Any = None) -> Any:
    """
    Validate and normalize config for a plugin runtime before it starts matching TS resolveConfig.
    """
    schema = getattr(runtime, "Config", None) if runtime is not None else getattr(plugin, "Config", None)
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
        if parent_ctx:
            self.entry = getattr(parent_ctx, "entry", None)
        if self.entry is not None:
            self.entry.fiber = self
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
        self._in_flight_effects: Set[asyncio.Task] = set()
        self._plugin_cls: Optional[Any] = None

        if runtime is not None:
            # Plugin Fiber
            if hasattr(parent_ctx, "registry"):
                self.uid = parent_ctx.registry.counter
            else:
                Fiber._uid_counter += 1
                self.uid = Fiber._uid_counter
            ext_dict = {"fiber": self}
            if self.entry is not None:
                ext_dict["entry"] = self.entry
            self.ctx = parent_ctx.extend(ext_dict) if parent_ctx else None
            self.state = FiberState.PENDING
            if self.inject and self.ctx:
                parent_intercept = getattr(parent_ctx, "_intercept_map", {}) if parent_ctx else {}
                self.ctx._intercept_map = dict(parent_intercept)
                for name, config in self.inject.items():
                    if config is not None:
                        self.ctx._intercept_map[name] = config

            if runtime is not None:
                runtime.add_fiber(self)

            parent_fiber = getattr(parent_ctx, "fiber", None) if parent_ctx else None
            if parent_fiber is not None and parent_fiber is not self:
                parent_fiber.effect(lambda: (lambda: self.dispose()), label="ctx.plugin()")

            try:
                if self.ctx and hasattr(self.ctx, "emit"):
                    self.ctx.emit("internal/plugin", self)
            except Exception as error:
                if runtime is not None:
                    runtime.remove_fiber(self)
                    if not runtime.fibers and parent_ctx and hasattr(parent_ctx, "registry"):
                        parent_ctx.registry._runtimes.pop(runtime.callback, None)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.dispose())
                except RuntimeError:
                    pass
                raise error
        else:
            # Root Fiber (runtime is None)
            self.uid = 0
            self.ctx = parent_ctx
            self.state = FiberState.ACTIVE
            self.epoch = ""

    @property
    def name(self) -> str:
        fiber = self
        while fiber is not None:
            if getattr(fiber, "runtime", None) and getattr(fiber.runtime, "name", None):
                return fiber.runtime.name
            parent_ctx = getattr(fiber, "parent", None)
            if not parent_ctx:
                break
            parent_fiber = getattr(parent_ctx, "fiber", None)
            if parent_fiber is fiber or parent_fiber is None:
                break
            fiber = parent_fiber
        return "root"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in ("uid", "ctx", "config", "_config", "state", "dispose", "store", "inertia", "epoch", "parent", "plugin", "runtime", "inject"):
            raise AttributeError(f"'Fiber' object has no attribute '{name}'")
        if self.plugin is not None and hasattr(self.plugin, name):
            return getattr(self.plugin, name)
        raise AttributeError(f"'Fiber' object has no attribute '{name}'")

    def __await__(self):
        return self.await_settled().__await__()

    def assert_active(self, check_error: bool = False) -> None:
        if self.uid is None:
            raise CordisError("INACTIVE_EFFECT")
        if check_error and self._error is not None:
            raise self._error

    def _resolve_config(self, config: Any) -> Any:
        """Resolve raw plugin config through internal/config waterfall matching TS."""
        if self.ctx and hasattr(self.ctx, "waterfall_sync"):
            config = self.ctx.waterfall_sync("internal/config", config, caller_ctx=self.ctx)
        target = self.plugin or getattr(self, "_plugin_cls", None) or (self.runtime.callback if self.runtime else None)
        return resolve_config(target, config, runtime=self.runtime)

    def effect(self, execute_or_disposer: Any, label: str = "anonymous", is_disposer: bool = False) -> Callable[[], Any]:
        """
        Register a cleanup-aware effect on this fiber.
        Supports functions, generators, async generators, and coroutines.
        Handles setup rollback on failure and barrier synchronization.
        """
        self.assert_active(check_error=False)
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
        wrapper: Optional[Any] = None
        remove_wrapper: Optional[Callable[[], bool]] = None

        def collect_disposer(disp: Any) -> None:
            if callable(disp):
                disposables.append(disp)

        def rollback_sync() -> None:
            nonlocal remove_wrapper, wrapper
            if wrapper is not None:
                self._effect_metas.pop(wrapper, None)
            if remove_wrapper is not None:
                remove_wrapper()
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
                            t = loop.create_task(res)
                            if hasattr(self, "_in_flight_effects"):
                                self._in_flight_effects.add(t)
                                t.add_done_callback(lambda task: self._in_flight_effects.discard(task))
                        except RuntimeError:
                            pass
                except Exception as e:
                    if self.ctx and hasattr(self.ctx, "logger"):
                        self.ctx.logger("fiber").error("Exception in effect rollback '%s': %s", label, e)

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
            nonlocal disposed, in_flight_cleanup, remove_wrapper, wrapper
            if disposed:
                return in_flight_cleanup
            disposed = True
            self._effect_metas.pop(cancel_effect, None)
            if wrapper is not None:
                self._effect_metas.pop(wrapper, None)
            if remove_wrapper is not None:
                remove_wrapper()

            if executing:
                barrier = wait_for_setup()
                async def _dispose_after_barrier():
                    if barrier is not None:
                        try:
                            await barrier
                        except Exception:
                            pass
                    while disposables:
                        disp = disposables.pop()
                        self._disposables.delete(disp)
                        try:
                            r = disp()
                            if inspect.isawaitable(r):
                                await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception in disposer '%s': %s", label, err)

                try:
                    loop = asyncio.get_running_loop()
                    in_flight_cleanup = loop.create_task(_dispose_after_barrier())
                    if hasattr(self, "_in_flight_effects"):
                        self._in_flight_effects.add(in_flight_cleanup)
                        in_flight_cleanup.add_done_callback(lambda t: self._in_flight_effects.discard(t))
                    return in_flight_cleanup
                except RuntimeError:
                    while disposables:
                        disp = disposables.pop()
                        self._disposables.delete(disp)
                        try:
                            r = disp()
                            if inspect.isawaitable(r):
                                pass
                        except Exception:
                            pass
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
                        self.ctx.logger("fiber").error("Exception running disposer '%s': %s", label, e)
                    else:
                        sys.stderr.write(f"[Cordis Fiber Error] Exception running disposer '{label}': {e}\n")

            if async_disposers or (setup_task and not setup_task.done()):
                async def _run_cleanup():
                    if setup_task and not setup_task.done():
                        try:
                            await setup_task
                        except Exception:
                            pass
                    for r in async_disposers:
                        try:
                            await r
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception in async disposer '%s': %s", label, err)

                try:
                    loop = asyncio.get_running_loop()
                    in_flight_cleanup = loop.create_task(_run_cleanup())
                    if hasattr(self, "_in_flight_effects"):
                        self._in_flight_effects.add(in_flight_cleanup)
                        in_flight_cleanup.add_done_callback(lambda t: self._in_flight_effects.discard(t))
                    return in_flight_cleanup
                except RuntimeError:
                    for r in async_disposers:
                        try:
                            pass
                        except Exception:
                            pass
                    return None
            return None

        class _EffectWrapper:
            def __init__(self, c_fn: Callable[[], Any], get_task: Callable[[], Optional[asyncio.Task]]):
                self._c_fn = c_fn
                self._get_task = get_task

            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                t = self._get_task()
                if t is not None and not t.done():
                    async def _call_after():
                        try:
                            await t
                        except Exception:
                            pass
                        res = self._c_fn(*args, **kwargs)
                        if inspect.isawaitable(res):
                            return await res
                        return res
                    return _call_after()
                return self._c_fn(*args, **kwargs)

            def __await__(self):
                async def _await_wrapper():
                    t = self._get_task()
                    if t is not None and not t.done():
                        try:
                            await t
                        except Exception:
                            pass
                    res = self._c_fn()
                    if inspect.isawaitable(res):
                        return await res
                    return res
                return _await_wrapper().__await__()

        wrapper = _EffectWrapper(cancel_effect, lambda: setup_task)
        self._effect_metas[wrapper] = meta
        self._effect_metas[cancel_effect] = meta
        remove_wrapper = self._disposables.push(wrapper)

        if is_disposer:
            if callable(execute_or_disposer):
                collect_disposer(execute_or_disposer)
            elif execute_or_disposer is not None:
                raise TypeError("Invalid effect")
            if setup_barrier_future and not setup_barrier_future.done():
                setup_barrier_future.set_result(None)
        elif callable(execute_or_disposer):
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
                        if hasattr(self, "_in_flight_effects"):
                            self._in_flight_effects.add(setup_task)
                            setup_task.add_done_callback(lambda t: self._in_flight_effects.discard(t))
                    except RuntimeError:
                        pass
                elif res is None:
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
                    old_epoch = self.epoch
                    async def _consume_async_gen():
                        try:
                            async for item in res:
                                if self.epoch != old_epoch:
                                    break
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
                        if hasattr(self, "_in_flight_effects"):
                            self._in_flight_effects.add(setup_task)
                            setup_task.add_done_callback(lambda t: self._in_flight_effects.discard(t))
                    except RuntimeError:
                        pass
                else:
                    raise TypeError("Invalid effect")
            except Exception as e:
                executing = False
                setup_failed = True
                self._effect_metas.pop(cancel_effect, None)
                self._effect_metas.pop(wrapper, None)
                if setup_barrier_future and not setup_barrier_future.done():
                    setup_barrier_future.set_exception(e)
                rollback_sync()
                if self.ctx and hasattr(self.ctx, "logger"):
                    self.ctx.logger("fiber").error("Exception in effect execution '%s': %s", label, e)
                raise e
        else:
            raise TypeError("Invalid effect")
        executing = False

        return wrapper

    def disposable(self, disposer: Callable[[], Any], label: str = "") -> Callable[[], None]:
        """Register a pure cleanup/teardown disposer on this fiber without executing it at setup."""
        return self.effect(disposer, label=label, is_disposer=True)

    def get_effects(self) -> List[Dict[str, Any]]:
        """Return metadata for currently registered effects matching TS Fiber.getEffects."""
        seen = set()
        metas = []
        for d in self._disposables:
            meta = self._effect_metas.get(d)
            if meta is not None and id(meta) not in seen:
                seen.add(id(meta))
                metas.append(meta.to_dict() if hasattr(meta, "to_dict") else meta)
        return metas

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
        from dsh.cordis.utils import get_traceable
        impl = self.ctx.reflect._get_impl(self.ctx, name, strict=True)
        if not impl:
            self._store.pop(name, None)
            return
        try:
            if impl.check and callable(impl.check):
                traceable_val = get_traceable(self.ctx, impl.value)
                try:
                    passed = impl.check(traceable_val)
                except TypeError:
                    passed = impl.check()
                if not passed:
                    self._store.pop(name, None)
                    return
        except Exception as e:
            if hasattr(impl, "fiber") and impl.fiber and impl.fiber.ctx and hasattr(impl.fiber.ctx, "logger"):
                impl.fiber.ctx.logger("fiber").error("Exception checking impl availability for '%s': %s", name, e)
            elif self.ctx and hasattr(self.ctx, "logger"):
                self.ctx.logger("fiber").error("Exception checking impl availability for '%s': %s", name, e)
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
        for name in self.inject.keys():
            impl = self._store.get(name)
            if not impl:
                epoch = INACTIVE_EPOCH
                break
            fib = getattr(impl, "fiber", None)
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

    def _instantiate_plugin(self) -> Any:
        cls = getattr(self, "_plugin_cls", None)
        if cls is None:
            return self.plugin
        from dsh.cordis.service import Service
        from dsh.cordis.plugin import Plugin

        init_fn = getattr(cls, "__init__", None)
        if init_fn is object.__init__ or init_fn is None:
            inst = cls()
            if hasattr(inst, "ctx") and getattr(inst, "ctx", None) is None:
                inst.ctx = self.ctx
            return inst

        try:
            sig = inspect.signature(init_fn)
            params = [p for name, p in sig.parameters.items() if name != "self" and p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
            param_names = [name for name in sig.parameters.keys() if name != "self"]
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        except (ValueError, TypeError):
            params = []
            param_names = []
            has_varargs = False
            has_varkw = False

        if issubclass(cls, Service):
            if "config" in param_names or ("cfg" in param_names) or has_varkw:
                return cls(self.ctx, config=self.config)
            elif len(params) >= 1 or "ctx" in param_names or has_varargs:
                return cls(self.ctx)
            else:
                return cls()
        elif issubclass(cls, Plugin):
            if len(params) >= 1 or "config" in param_names or has_varargs or has_varkw:
                inst = cls(config=self.config)
            else:
                inst = cls()
            inst.ctx = self.ctx
            return inst
        else:
            if len(params) >= 2 or has_varargs or ("ctx" in param_names and "config" in param_names):
                inst = cls(self.ctx, config=self.config)
            elif len(params) == 1:
                p_name = params[0].name
                if p_name in ("config", "cfg"):
                    inst = cls(config=self.config)
                else:
                    inst = cls(self.ctx)
            elif has_varkw:
                inst = cls(self.ctx, config=self.config)
            else:
                inst = cls()
            if hasattr(inst, "ctx") and getattr(inst, "ctx", None) is None:
                inst.ctx = self.ctx
            return inst

    def _reload(self) -> None:
        """Execute plugin apply and transition to ACTIVE on success."""
        epoch = self.epoch
        try:
            self.store = dict(self._store)
            self.config = self._resolve_config(self._config)
            if getattr(self, "_plugin_cls", None) is not None:
                self.plugin = self._instantiate_plugin()

            if hasattr(self.plugin, "config") and self.config is not None:
                self.plugin.config = self.config
            if hasattr(self.plugin, "ctx"):
                from dsh.cordis.loader import EntryTree
                if not isinstance(self.plugin, EntryTree):
                    self.plugin.ctx = self.ctx

            # 1:1 Execute init hooks and symbols.init matching TS Fiber execute
            init_hooks = getattr(self.plugin, symbols.initHooks, None) or getattr(self.plugin, "_init_hooks", [])
            for hook in list(init_hooks):
                if callable(hook):
                    hook()

            init_fn = getattr(self.plugin, symbols.init, None)
            if not callable(init_fn) and hasattr(self.plugin, "init"):
                raw_init = getattr(self.plugin, "init")
                if callable(raw_init):
                    init_fn = raw_init

            if init_fn and callable(init_fn):
                init_res = init_fn()
                is_async_iter = inspect.isasyncgen(init_res) or hasattr(init_res, "__aiter__")
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if is_async_iter and (loop is not None or not hasattr(init_res, "__iter__")):
                    async def _run_async_init(gen=init_res):
                        try:
                            async for item in gen:
                                if callable(item):
                                    self.disposable(item)
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
                            self.set_state(FiberState.FAILED)
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception during async init in fiber '%s': %s", self.name, e)
                            self.set_state(FiberState.UNLOADING)
                            self._unload()

                    if loop is not None:
                        self.inertia = loop.create_task(_run_async_init())
                        return
                elif inspect.isgenerator(init_res) or hasattr(init_res, "__iter__"):
                    for item in init_res:
                        if callable(item):
                            self.disposable(item)
                elif inspect.iscoroutine(init_res):
                    async def _run_coro_init(coro=init_res):
                        try:
                            ret = await coro
                            if callable(ret):
                                self.disposable(ret)
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
                            self.set_state(FiberState.FAILED)
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception during coro init in fiber '%s': %s", self.name, e)
                            self.set_state(FiberState.UNLOADING)
                            self._unload()

                    try:
                        loop = asyncio.get_running_loop()
                        self.inertia = loop.create_task(_run_coro_init())
                        return
                    except RuntimeError:
                        pass

            def _invoke_apply(fn: Callable[..., Any]) -> Any:
                call_single = False
                try:
                    sig = inspect.signature(fn)
                    params = [p for name, p in sig.parameters.items() if name != "self" and p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
                    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    if len(params) == 1 and not has_varargs:
                        call_single = True
                except (ValueError, TypeError):
                    pass
                if call_single:
                    return fn(self.ctx)
                return fn(self.ctx, self.config)

            res = None
            from dsh.cordis.service import Service
            if hasattr(self.plugin, "apply") and callable(self.plugin.apply):
                res = _invoke_apply(self.plugin.apply)
            elif isinstance(self.plugin, dict) and callable(self.plugin.get("apply")):
                res = _invoke_apply(self.plugin["apply"])
            elif not isinstance(self.plugin, Service) and callable(self.plugin):
                res = _invoke_apply(self.plugin)

            if res is not None:
                if inspect.isawaitable(res):
                    async def _async_wait_res():
                        try:
                            ret = await res
                            if callable(ret):
                                self.disposable(ret)
                            elif inspect.isgenerator(ret) or inspect.isasyncgen(ret):
                                self.effect(lambda r=ret: r, label=f"apply({self.name})")
                            elif ret is not None:
                                raise TypeError("Invalid effect")
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
                            self.set_state(FiberState.FAILED)
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception during async apply in fiber '%s': %s", self.name, e)
                            else:
                                sys.stderr.write(f"[Cordis Fiber Error] Exception during async apply in fiber '{self.name}': {e}\n")
                            self.set_state(FiberState.UNLOADING)
                            self._unload()
                    try:
                        loop = asyncio.get_running_loop()
                        self.inertia = loop.create_task(_async_wait_res())
                        return
                    except RuntimeError:
                        ret = asyncio.run(res)
                        if callable(ret):
                            self.disposable(ret)
                        elif inspect.isgenerator(ret) or inspect.isasyncgen(ret):
                            self.effect(lambda r=ret: r, label=f"apply({self.name})")
                        elif ret is not None:
                            raise TypeError("Invalid effect")
                elif inspect.isgenerator(res) or inspect.isasyncgen(res):
                    self.effect(lambda r=res: r, label=f"apply({self.name})")
                elif callable(res):
                    self.disposable(res)
                elif res is not None:
                    raise TypeError("Invalid effect")

            self._error = None
            self.set_state(FiberState.ACTIVE)
        except Exception as e:
            self._error = e
            self.epoch = INACTIVE_EPOCH
            self.set_state(FiberState.FAILED)
            if self.ctx and hasattr(self.ctx, "logger"):
                self.ctx.logger("fiber").error("Exception during apply in fiber '%s': %s", self.name, e)
            else:
                sys.stderr.write(f"[Cordis Fiber Error] Exception during apply in fiber '{self.name}': {e}\n")

        if self.epoch != epoch:
            self.set_state(FiberState.UNLOADING)
            self._unload()

    def _get_state(self) -> FiberState:
        if self.uid is None:
            return FiberState.DISPOSED
        if self._error is not None:
            return FiberState.FAILED
        if self.epoch != INACTIVE_EPOCH:
            return FiberState.ACTIVE
        return FiberState.PENDING

    def _unload(self) -> None:
        """Execute all disposers and transition state."""
        disposers = self._disposables.clear()
        self._effect_metas.clear()
        if not disposers:
            self.store = None
            if self.epoch == INACTIVE_EPOCH:
                self.set_state(self._get_state())
                self.inertia = None
            else:
                self.set_state(FiberState.LOADING)
                self._reload()
            return

        async_disposers = []
        for disposer in disposers:
            try:
                res = disposer()
                if inspect.isawaitable(res):
                    async_disposers.append(res)
            except Exception as e:
                if self.ctx and hasattr(self.ctx, "logger"):
                    self.ctx.logger("fiber").error("Exception during unload for '%s': %s", self.name, e)
                else:
                    sys.stderr.write(f"[Cordis Fiber Error] Exception during unload for '{self.name}': {e}\n")

        if not async_disposers:
            self.store = None
            if self.epoch == INACTIVE_EPOCH:
                self.set_state(self._get_state())
                self.inertia = None
            else:
                self.set_state(FiberState.LOADING)
                self._reload()
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            async def _run_gather():
                try:
                    results = await asyncio.gather(*async_disposers, return_exceptions=True)
                    for r in results:
                        if isinstance(r, Exception):
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception during async unload for '%s': %s", self.name, r)
                            else:
                                sys.stderr.write(f"[Cordis Fiber Error] Exception during async unload for '{self.name}': {r}\n")
                finally:
                    self.store = None
                    if self.epoch == INACTIVE_EPOCH:
                        self.set_state(self._get_state())
                        self.inertia = None
                    else:
                        self.set_state(FiberState.LOADING)
                        self._reload()

            self.inertia = loop.create_task(_run_gather())
            if hasattr(self, "_in_flight_effects"):
                self._in_flight_effects.add(self.inertia)
                self.inertia.add_done_callback(lambda t: self._in_flight_effects.discard(t))
        else:
            for r in async_disposers:
                try:
                    asyncio.run(r)
                except Exception:
                    pass
            self.store = None
            if self.epoch == INACTIVE_EPOCH:
                self.set_state(self._get_state())
                self.inertia = None
            else:
                self.set_state(FiberState.LOADING)
                self._reload()

    def _emit_plugin_disposed(self) -> None:
        if not self.ctx:
            return
        bus = getattr(self.ctx, "_event_bus", None)
        if not bus:
            return
        try:
            callbacks = bus._dispatch_hooks("emit", "internal/plugin", self, caller_ctx=self.ctx)
        except Exception as e:
            if hasattr(self.ctx, "logger"):
                try:
                    self.ctx.logger.error(e)
                except Exception:
                    pass
            return
        for cb in callbacks:
            try:
                res = cb(self)
                if inspect.isawaitable(res):
                    def _catch_err(f):
                        try:
                            f.result()
                        except Exception as err:
                            if hasattr(self.ctx, "logger"):
                                try:
                                    self.ctx.logger.error(err)
                                except Exception:
                                    pass
                    task = asyncio.ensure_future(res)
                    task.add_done_callback(_catch_err)
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    try:
                        self.ctx.logger.error(e)
                    except Exception:
                        pass

    async def dispose(self) -> None:
        """Dispose this fiber and execute disposers in strict reverse order matching TS fiber.dispose."""
        if self.runtime is None:
            self.set_state(FiberState.UNLOADING)
            self._unload()
            while self.inertia is not None and not self.inertia.done():
                await self.inertia
            self.set_state(FiberState.ACTIVE)
            return

        if getattr(self, "_disposing", False) or self.state == FiberState.DISPOSED:
            return
        self._disposing = True

        self.uid = None
        self._emit_plugin_disposed()

        # Remove from runtime.fibers and registry if empty
        if self.runtime is not None:
            registry = getattr(self.ctx, "registry", None)
            if registry is not None and hasattr(registry, "has") and registry.has(self.runtime.callback):
                try:
                    self.runtime.remove_fiber(self)
                except (ValueError, KeyError, AttributeError):
                    pass
                if not self.runtime.fibers:
                    if hasattr(registry, "_runtimes"):
                        registry._runtimes.pop(self.runtime.callback, None)

        self.set_epoch(INACTIVE_EPOCH)
        if hasattr(self, "_in_flight_effects"):
            for t in list(self._in_flight_effects):
                if not t.done():
                    try:
                        await t
                    except Exception:
                        pass
        if not self.inertia or self.inertia.done():
            self.set_state(FiberState.UNLOADING)
            self._unload()
        while self.inertia is not None and not self.inertia.done():
            await self.inertia

        self.set_state(FiberState.DISPOSED)

    def update(self, config: Any, no_save: bool = False) -> Any:
        """
        Validate and apply new config, then restart the plugin via internal/update waterfall.
        Matching TS Fiber.update(config, noSave).
        """
        self.assert_active(check_error=False)
        self._config = config
        if self.state != FiberState.ACTIVE:
            self._error = None
            self.set_epoch(INACTIVE_EPOCH)
            self._refresh()
            return None

        resolved_config = self._resolve_config(config)

        def _do_update(cfg=resolved_config):
            self.config = cfg
            self._error = None
            return self.restart()

        if hasattr(self.ctx, "waterfall"):
            try:
                loop = asyncio.get_running_loop()
                return self.ctx.waterfall("internal/update", resolved_config, no_save, _do_update, caller_ctx=self.ctx)
            except RuntimeError:
                return self.ctx.waterfall_sync("internal/update", resolved_config, no_save, _do_update, caller_ctx=self.ctx)
        return _do_update()

    def restart(self) -> Any:
        """Dispose and immediately reload this plugin matching TS fiber.restart()."""
        self.assert_active()
        self.set_epoch(INACTIVE_EPOCH)
        self._refresh()

        async def _do_restart() -> "Fiber":
            await self.await_settled()
            return self

        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(_do_restart())
        except RuntimeError:
            class _SyncResolvedFuture:
                def __init__(self, result: Any):
                    self._result = result
                def __await__(self):
                    async def _coro():
                        return self._result
                    return _coro().__await__()
                def result(self):
                    return self._result
                def done(self):
                    return True
                def add_done_callback(self, fn: Callable[..., Any]):
                    fn(self)

            return _SyncResolvedFuture(self)

    async def await_settled(self) -> "Fiber":
        """Wait for current lifecycle transitions to settle."""
        while self.inertia is not None and not self.inertia.done():
            await self.inertia
        if hasattr(self, "_in_flight_effects"):
            for t in list(self._in_flight_effects):
                if not t.done():
                    try:
                        await t
                    except Exception:
                        pass
        if self._error:
            raise self._error
        return self

    await_ = await_settled

    def __repr__(self) -> str:
        return f"<Fiber {self.name} uid={self.uid} state={self.state} epoch={self.epoch}>"
