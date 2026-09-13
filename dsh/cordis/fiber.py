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


def is_sync_iterable_effect(value: Any) -> bool:
    """
    Return whether an effect result is a synchronous iterable of disposers.

    Mirrors the `Symbol.iterator in effect` branch of `Fiber._execute`
    (fiber.ts:375): a JavaScript primitive is not an object and therefore can
    never be an effect, so the Python stand-ins for primitives (str/bytes) are
    rejected instead of being iterated character by character. Any other object
    exposing the synchronous iteration protocol is accepted.
    """
    if isinstance(value, (str, bytes, bytearray)):
        return False
    return hasattr(value, "__iter__")


def run_async_setup_sync(coro: Any) -> Any:
    """
    Drive an async effect setup to completion when no event loop is running.

    `fiber.ts` `_execute` always adopts an async effect body (`effect.then(
    safeCollect)` for the thenable branch, the awaited try/catch for the
    `Symbol.asyncIterator` branch) because JavaScript always has a microtask
    queue. A synchronous Python caller (`ctx.effect(async_setup)` outside a
    running loop) has no ambient loop, so the same coroutine is driven to
    completion on a private loop. The effect therefore still runs, its disposers
    are still owned by the fiber, and no unawaited coroutine is leaked. Errors
    are already logged and rolled back by the effect body; they are not
    re-raised, matching the reference where an async setup failure only settles
    the effect's promise (the public disposer/`then` chain) and never throws out
    of `effect()` itself.
    """
    try:
        return asyncio.run(coro)
    except Exception:
        return None


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
        # The parent-owned `ctx.plugin()` effect wrapper, whose disposer
        # `fiber.ts` assigns to `this.dispose`: disposing a child retires the
        # registration, and the child teardown is that effect's cleanup.
        self._parent_disposer: Optional[Any] = None
        # Records what the last `set_epoch()` call drove; reset on every call.
        self._epoch_transition_driven = False
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
                # fiber.ts `Object.create(parent[Context.intercept])`: the new
                # context owns only the entries its own inject declarations add;
                # the parent's entries stay reachable through `_parent`.
                self.ctx._intercept_map = {}
                for name, config in self.inject.items():
                    if config is not None:
                        self.ctx._intercept_map[name] = config

            if runtime is not None:
                runtime.add_fiber(self)

            parent_fiber = getattr(parent_ctx, "fiber", None) if parent_ctx else None
            if parent_fiber is not None and parent_fiber is not self:
                # `fiber.ts` constructor: `this.dispose = parent.fiber.effect(
                # () => {...}, 'ctx.plugin()')`. The parent owns the removal
                # record, this fiber's teardown is that effect's cleanup, and
                # `dispose()` retires the record so a disposed child is no
                # longer owned by (or re-disposed through) its parent.
                self._parent_disposer = parent_fiber.effect(
                    lambda: (lambda: self.dispose()), label="ctx.plugin()"
                )

            try:
                if self.ctx and hasattr(self.ctx, "emit"):
                    self.ctx.emit("internal/plugin", self)
            except Exception as error:
                self._rollback_failed_publication()
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
        retired = False
        wrapper: Optional[Any] = None
        remove_wrapper: Optional[Callable[[], bool]] = None

        def collect_disposer(disp: Any) -> None:
            if callable(disp):
                disposables.append(disp)
                # fiber.ts `collect`: this effect takes ownership of a disposer the
                # fiber list also held (a nested effect), so the fiber no longer
                # owns it and its metadata nests under this effect.
                self._disposables.delete(disp)
                nested = self._effect_metas.get(disp)
                if nested is not None and nested is not meta:
                    meta.children.append(nested)

        def safe_collect(produced: Any) -> None:
            """
            Mirror fiber.ts `_execute` `safeCollect` for values produced by an effect.

            A produced value is a disposer only when it is callable; every other
            non-null value is an invalid effect and fails the registration, which
            makes the caller roll the already-collected disposers back.
            """
            if callable(produced):
                collect_disposer(produced)
            elif produced is not None:
                raise TypeError("Invalid effect")

        def retire_in_flight(task: asyncio.Task) -> None:
            """
            Drop a finished effect task and mark its failure as reported.

            A setup task nobody awaits must not surface later as an unretrieved
            task exception; the reference logs the failure inside the task chain.
            """
            self._in_flight_effects.discard(task)
            if not task.cancelled():
                task.exception()

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
                                t.add_done_callback(retire_in_flight)
                        except RuntimeError:
                            # Rollback of a synchronous caller has no loop to
                            # schedule the async disposer on; run it to
                            # completion so the rollback reaches quiescence.
                            run_async_setup_sync(res)
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

        def retire_effect() -> None:
            """
            Drop this effect from its owner fiber without running its cleanups.

            `fiber.ts` removes the parent-owned wrapper through the
            `removeWrapper()` closure that `finalizeDisposal` calls: immediately
            for a synchronous teardown, and from the cleanup promise's `finally`
            when the teardown is asynchronous. The port starts the teardown at
            the call site, so it retires the record with the same rule: while an
            async cleanup is in flight `getEffects()` keeps reporting the
            effect, a later owner unload joins the cleanup instead of disposing
            the effect a second time, and only settlement drops the record.
            """
            nonlocal retired
            if retired:
                return
            retired = True
            self._effect_metas.pop(cancel_effect, None)
            if wrapper is not None:
                self._effect_metas.pop(wrapper, None)
            if remove_wrapper is not None:
                remove_wrapper()

        def cancel_effect() -> Any:
            nonlocal disposed, in_flight_cleanup, remove_wrapper, wrapper
            if disposed:
                return in_flight_cleanup
            disposed = True

            if executing:
                barrier = wait_for_setup()
                async def _dispose_after_barrier():
                    try:
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
                    finally:
                        # fiber.ts `finalizeDisposal` removes the owner-list entry
                        # from the cleanup promise's `finally`, so the teardown a
                        # caller awaits only settles once the effect is retired.
                        retire_effect()

                try:
                    loop = asyncio.get_running_loop()
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
                    retire_effect()
                    return None

                in_flight_cleanup = loop.create_task(_dispose_after_barrier())
                if hasattr(self, "_in_flight_effects"):
                    self._in_flight_effects.add(in_flight_cleanup)
                    in_flight_cleanup.add_done_callback(retire_in_flight)
                return in_flight_cleanup

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
                    try:
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
                    finally:
                        # Same `finalizeDisposal` rule as the barrier teardown: the
                        # owner-list entry outlives the cleanup and is dropped with
                        # it, so awaiting this task also awaits retirement.
                        retire_effect()

                try:
                    loop = asyncio.get_running_loop()
                    in_flight_cleanup = loop.create_task(_run_cleanup())
                    if hasattr(self, "_in_flight_effects"):
                        self._in_flight_effects.add(in_flight_cleanup)
                        in_flight_cleanup.add_done_callback(retire_in_flight)
                    return in_flight_cleanup
                except RuntimeError:
                    # A synchronous caller (for example `ctx.teardown()` invoked
                    # outside a task) has no loop to schedule the cleanup on;
                    # drain it on a fresh loop so disposal still reaches
                    # quiescence before returning.
                    for r in async_disposers:
                        try:
                            if inspect.iscoroutine(r):
                                asyncio.run(r)
                            else:
                                new_loop = asyncio.new_event_loop()
                                try:
                                    new_loop.run_until_complete(r)
                                finally:
                                    new_loop.close()
                        except Exception as err:
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception in async disposer '%s': %s", label, err)
                            else:
                                sys.stderr.write(f"[Cordis Fiber Error] Exception in async disposer '{label}': {err}\n")
                    retire_effect()
                    return None
            retire_effect()
            return None

        class _EffectWrapper:
            """
            Public disposer returned by `effect()`, matching the reference wrapper.

            Calling it tears the effect down; when async setup is still running the
            call waits for it first and rethrows its failure after cleanup. Awaiting
            it waits for setup and resolves with the disposer, so a caller that needs
            the effect live still receives the teardown handle.
            """

            def __init__(self, c_fn: Callable[[], Any], get_task: Callable[[], Optional[asyncio.Task]],
                         retire_fn: Callable[[], None]):
                self._c_fn = c_fn
                self._get_task = get_task
                self.retire = retire_fn

            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                t = self._get_task()
                if t is not None and not t.done():
                    async def _call_after():
                        try:
                            await t
                        except Exception:
                            res = self._c_fn(*args, **kwargs)
                            if inspect.isawaitable(res):
                                await res
                            raise
                        res = self._c_fn(*args, **kwargs)
                        if inspect.isawaitable(res):
                            return await res
                        return res
                    return _call_after()
                return self._c_fn(*args, **kwargs)

            def __await__(self):
                # fiber.ts `wrapper.then`: wait for the setup task, then hand
                # the caller the disposer. Running it stays the caller's
                # decision -- awaiting a registration must not tear it down.
                async def _await_wrapper():
                    t = self._get_task()
                    if t is not None:
                        await t
                    return self._c_fn
                return _await_wrapper().__await__()

        wrapper = _EffectWrapper(cancel_effect, lambda: setup_task, retire_effect)
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
                            setup_task.add_done_callback(retire_in_flight)
                    except RuntimeError:
                        # No ambient loop: drive the setup now so the effect is
                        # adopted instead of leaking an unawaited coroutine.
                        run_async_setup_sync(_await_async_setup())
                elif res is None:
                    if setup_barrier_future and not setup_barrier_future.done():
                        setup_barrier_future.set_result(None)
                elif is_sync_iterable_effect(res):
                    # fiber.ts `_execute` `Symbol.iterator in effect` branch: the
                    # iterable is drained synchronously and every produced value is
                    # run through `safeCollect`. The iterator is stepped by hand so
                    # the terminal `{ value, done: true }` result is collected too,
                    # exactly like `safeCollect(result.value)` before the `done`
                    # check. A throw from iteration or from `safeCollect` rolls the
                    # already-collected disposers back in reverse order.
                    try:
                        iterator = iter(res)
                        while True:
                            try:
                                item = next(iterator)
                            except StopIteration as stop:
                                safe_collect(stop.value)
                                break
                            safe_collect(item)
                        if setup_barrier_future and not setup_barrier_future.done():
                            setup_barrier_future.set_result(None)
                    except Exception as gen_err:
                        rollback_sync()
                        if setup_barrier_future and not setup_barrier_future.done():
                            setup_barrier_future.set_exception(gen_err)
                        raise gen_err
                elif hasattr(res, "__aiter__"):
                    # fiber.ts `_execute` `Symbol.asyncIterator in effect` branch:
                    # any async iterable is drained on a task with the load-epoch
                    # re-check, collecting each produced disposer on this effect.
                    old_epoch = self.epoch
                    async def _consume_async_iter():
                        try:
                            async for item in res:
                                if self.epoch != old_epoch:
                                    break
                                safe_collect(item)
                            if setup_barrier_future and not setup_barrier_future.done():
                                setup_barrier_future.set_result(None)
                        except Exception as async_iter_err:
                            # Re-raise so the setup task rejects like the reference
                            # `_execute` asyncIterator promise, which is what the
                            # public disposer's `then` chain reports to its caller.
                            rollback_sync()
                            if setup_barrier_future and not setup_barrier_future.done():
                                setup_barrier_future.set_exception(async_iter_err)
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception consuming async iterable '%s': %s", label, async_iter_err)
                            raise async_iter_err
                    try:
                        loop = asyncio.get_running_loop()
                        setup_task = loop.create_task(_consume_async_iter())
                        if hasattr(self, "_in_flight_effects"):
                            self._in_flight_effects.add(setup_task)
                            setup_task.add_done_callback(retire_in_flight)
                    except RuntimeError:
                        # No ambient loop: drain the async iterable now (same
                        # reason as the thenable branch above).
                        run_async_setup_sync(_consume_async_iter())
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

    def _collect(self, dispose: Any) -> None:
        """
        Bind a disposer produced by the plugin body to this fiber.

        Mirrors the fiber-level `collect` in TS `Fiber._execute`: the disposer is
        pushed as given, so a nested effect wrapper keeps its own metadata while a
        plain function carries none. Any other produced value is rejected.
        """
        if callable(dispose):
            self._disposables.push(dispose)
        elif dispose is not None:
            raise TypeError("Invalid effect")

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
        self._epoch_transition_driven = False
        old_epoch = self.epoch
        if epoch == old_epoch:
            return
        self.epoch = epoch
        if self.inertia is not None and not self.inertia.done():
            return

        if epoch != INACTIVE_EPOCH and old_epoch == INACTIVE_EPOCH:
            self._epoch_transition_driven = True
            self._start_reload(epoch)
        elif epoch == INACTIVE_EPOCH and old_epoch != INACTIVE_EPOCH:
            self._epoch_transition_driven = True
            self.set_state(FiberState.UNLOADING)
            self._unload()
        elif epoch != INACTIVE_EPOCH and old_epoch != INACTIVE_EPOCH:
            self._epoch_transition_driven = True
            # Composite epoch changed due to upstream dependency restart/replacement -> reload!
            self.set_state(FiberState.UNLOADING)
            self._unload()

    # Names that identify the context / resolved-config slots of a plugin
    # constructor when only one positional parameter is accepted.
    _CTX_PARAM_NAMES = ("ctx", "context", "_ctx")
    _CONFIG_PARAM_NAMES = ("config", "cfg", "conf", "options", "opts", "settings")

    def _constructor_arguments(self, init_fn: Any) -> Any:
        """
        Build the positional/keyword arguments for a class-plugin constructor.

        `fiber.ts` `_runner.execute` always calls `new runtime.callback(this.ctx,
        this.config)`: the context goes into the first positional slot and the
        resolved config into the second. JavaScript silently drops surplus
        arguments and passes `undefined` for missing ones, while Python raises
        `TypeError` for both, so the accepted shape is read from the signature
        and the same two values are supplied positionally wherever the
        constructor can take them.
        """
        positionals = []
        keyword_only = []
        has_varargs = False
        has_varkw = False
        try:
            sig = inspect.signature(init_fn)
        except (ValueError, TypeError):
            # Uninspectable callable (C extension or builtin): use the upstream call.
            return (self.ctx, self.config), {}

        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                positionals.append(param)
            elif param.kind == inspect.Parameter.VAR_POSITIONAL:
                has_varargs = True
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                has_varkw = True
            elif param.kind == inspect.Parameter.KEYWORD_ONLY:
                keyword_only.append(param)

        kwargs: Dict[str, Any] = {}
        for param in keyword_only:
            if param.name in self._CTX_PARAM_NAMES:
                kwargs[param.name] = self.ctx
            elif param.name in self._CONFIG_PARAM_NAMES:
                kwargs[param.name] = self.config

        if has_varargs or len(positionals) >= 2:
            return (self.ctx, self.config), kwargs
        if len(positionals) == 1:
            p_name = positionals[0].name
            if p_name in self._CONFIG_PARAM_NAMES:
                return (self.config,), kwargs
            # `new callback(this.ctx, this.config)`: the first positional slot is
            # the context, so an unrecognized single parameter still receives it.
            return (self.ctx,), kwargs
        if has_varkw and not keyword_only:
            # `constructor(...args)`-style rest parameter: JavaScript hands over
            # both values, so a Python `**kwargs` constructor receives them too.
            return (), {"ctx": self.ctx, "config": self.config}
        return (), kwargs

    def _instantiate_plugin(self) -> Any:
        cls = getattr(self, "_plugin_cls", None)
        if cls is None:
            return self.plugin

        init_fn = getattr(cls, "__init__", None)
        if init_fn is object.__init__ or init_fn is None:
            inst = cls()
            if hasattr(inst, "ctx") and getattr(inst, "ctx", None) is None:
                inst.ctx = self.ctx
            return inst

        args, kwargs = self._constructor_arguments(init_fn)
        inst = cls(*args, **kwargs)
        if hasattr(inst, "ctx") and getattr(inst, "ctx", None) is None:
            inst.ctx = self.ctx
        return inst

    def _start_reload(self, epoch: str) -> None:
        """
        fiber.ts `_reload` entry: publish LOADING and snapshot the dependency
        store, then cross the first event-loop checkpoint before resolving
        config or executing the plugin body.

        `_reload()` runs synchronously up to its first `await Promise.resolve()`
        -- `this.store = { ...this._store }` -- and `_setEpoch()` assigns
        `this.state = callback()` only once that prefix has returned, so the
        LOADING status is published with the fresh dependency snapshot already in
        place and no plugin code having run.

        The composite epoch that authorized this load is re-checked after the
        checkpoint, so a disposer or dependency transition queued inside that
        window cancels the load before any plugin code runs. A loop-less
        caller has no checkpoint to cross: neither CPython 3.8 nor Windows 7
        offers an ambient microtask queue outside a running loop, so the load
        runs inline exactly as it did before.
        """
        self.store = dict(self._store)
        self.set_state(FiberState.LOADING)
        if self.uid is None or self.epoch != epoch:
            # A reentrant disposer invalidated this load while the LOADING
            # status was reported. fiber.ts re-checks the epoch after its
            # initial microtask and never runs the plugin body; the nested
            # transition already drove the unload this fiber needs.
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._reload(epoch)
            return

        async def _deferred_reload():
            # fiber.ts `await Promise.resolve()`: a fresh task takes its first
            # step at the next event-loop checkpoint, so the plugin body runs
            # exactly one checkpoint after `ctx.plugin()` reported LOADING.
            self._reload(epoch)

        self.inertia = loop.create_task(_deferred_reload())

    def _reload(self, epoch: Optional[str] = None) -> None:
        """
        Execute plugin apply and transition to ACTIVE on success.

        `epoch` is the composite dependency epoch captured before the
        checkpoint; a load invalidated in that window is dropped without
        resolving config or running plugin code (fiber.ts `_reload`).
        """
        if epoch is None:
            epoch = self.epoch
        if self.uid is None or self.epoch != epoch:
            # fiber.ts re-checks `this._runner.epoch === oldEpoch` after the
            # initial microtask: the plugin body never runs for a stale load,
            # and this state update drains whatever the fiber collected while
            # it was PENDING/LOADING.
            self.set_state(FiberState.UNLOADING)
            self._unload()
            return
        try:
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
                                    self._collect(item)
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
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
                            self._collect(item)
                elif inspect.iscoroutine(init_res):
                    async def _run_coro_init(coro=init_res):
                        try:
                            ret = await coro
                            if callable(ret):
                                self._collect(ret)
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
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
                # TS `_execute` tests `typeof effect === 'function'` first, so a returned
                # disposer that is also thenable (e.g. the wrapper from `ctx.provide()`)
                # is collected as an effect instead of being awaited and disposed.
                if callable(res):
                    self._collect(res)
                elif inspect.isawaitable(res):
                    async def _async_wait_res():
                        try:
                            ret = await res
                            # fiber.ts `_execute` `'then' in effect` branch:
                            # `effect.then(safeCollect)` accepts only a disposer
                            # or null from the awaited setup; anything else is an
                            # invalid effect.
                            if callable(ret):
                                self._collect(ret)
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
                            self._collect(ret)
                        elif ret is not None:
                            raise TypeError("Invalid effect")
                elif is_sync_iterable_effect(res):
                    # fiber.ts `_execute` `Symbol.iterator in effect`: the returned
                    # iterable (not only a generator) yields disposers that are
                    # collected on the fiber itself. The iterator is stepped by
                    # hand so the terminal `{ value, done: true }` result is
                    # collected too, exactly like `safeCollect(result.value)`
                    # before the `done` check.
                    iterator = iter(res)
                    while True:
                        try:
                            item = next(iterator)
                        except StopIteration as stop:
                            self._collect(stop.value)
                            break
                        self._collect(item)
                elif hasattr(res, "__aiter__"):
                    # fiber.ts `_execute` asyncIterator branch: yielded disposers
                    # belong to the fiber itself, and the fiber stays busy until
                    # the iterable is drained.
                    async def _collect_async_iter(gen: Any = res) -> None:
                        try:
                            async for item in gen:
                                if self.epoch != epoch:
                                    break
                                self._collect(item)
                            if self.epoch != epoch or self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
                                self.set_state(FiberState.UNLOADING)
                                self._unload()
                                return
                            self._error = None
                            self.set_state(FiberState.ACTIVE)
                        except Exception as e:
                            self._error = e
                            self.epoch = INACTIVE_EPOCH
                            if self.ctx and hasattr(self.ctx, "logger"):
                                self.ctx.logger("fiber").error("Exception consuming async apply in fiber '%s': %s", self.name, e)
                            else:
                                sys.stderr.write(f"[Cordis Fiber Error] Exception consuming async apply in fiber '{self.name}': {e}\n")
                            self.set_state(FiberState.UNLOADING)
                            self._unload()

                    try:
                        loop = asyncio.get_running_loop()
                        self.inertia = loop.create_task(_collect_async_iter())
                        return
                    except RuntimeError:
                        asyncio.run(_collect_async_iter())
                elif res is not None:
                    raise TypeError("Invalid effect")

            self._error = None
            self.set_state(FiberState.ACTIVE)
        except Exception as e:
            # fiber.ts `_reload` records the failure and invalidates the epoch,
            # then derives the state transition: the epoch is INACTIVE, so the
            # update drives UNLOADING, `_unload` drains the effects collected
            # before the failure, and only its final `_getState()` publishes
            # FAILED. Publishing FAILED here would emit a state the reference
            # never reaches.
            self._error = e
            self.epoch = INACTIVE_EPOCH
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
                self._start_reload(self.epoch)
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
                self._start_reload(self.epoch)
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
                        self._start_reload(self.epoch)

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
                self._start_reload(self.epoch)

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

    def dispose(self) -> Any:
        """
        Dispose this fiber and return an awaitable that settles once it is quiescent.

        Mirrors TS `fiber.dispose`, which *is* the parent-owned `ctx.plugin()`
        effect disposer (`fiber.ts` constructor assigns it to `this.dispose`).
        The teardown body starts at the call site -- clearing the uid,
        notifying `internal/plugin` observers, and starting disposers -- and
        the parent-owned registration is retired once that teardown settles,
        exactly like the reference `finalizeDisposal` chain calling
        `removeWrapper()` in its `finally`: the record stays owner-visible
        while the teardown is in flight, so an owner unload joins cleanup that
        another caller already started (`runDisposable` -> `effectInertia`)
        instead of disposing the child twice. Awaiting the returned object
        waits for teardown to finish. Disposers run in strict reverse
        registration order; a fiber without a parent (the root fiber) owns no
        registration.
        """
        self._begin_dispose()
        settled = self._await_quiescent()
        disposer = self._parent_disposer
        if disposer is None:
            return settled

        async def _retire_when_settled():
            try:
                await settled
            finally:
                disposer.retire()

        return _retire_when_settled()

    def _begin_dispose(self) -> None:
        """Run the part of TS `dispose` before its first await."""
        if self.runtime is None:
            self.set_state(FiberState.UNLOADING)
            self._unload()
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

    async def _await_quiescent(self) -> None:
        """Run the await tail of TS `dispose` for a teardown started by `_begin_dispose`."""
        if self.runtime is None:
            while self.inertia is not None and not self.inertia.done():
                await self.inertia
            self.set_state(FiberState.ACTIVE)
            return

        if hasattr(self, "_in_flight_effects"):
            for t in list(self._in_flight_effects):
                if not t.done():
                    try:
                        await t
                    except Exception:
                        pass
        # `set_epoch()` already drove the unload whenever the epoch changed. Only a
        # fiber whose epoch was already inactive (still PENDING, e.g. one owning
        # effects registered by an internal/plugin observer) needs this drain.
        if not self._epoch_transition_driven and (self.inertia is None or self.inertia.done()):
            self.set_state(FiberState.UNLOADING)
            self._unload()
        while self.inertia is not None and not self.inertia.done():
            await self.inertia

        self.set_state(FiberState.DISPOSED)

    def _rollback_failed_publication(self) -> None:
        """
        Dispose a child whose synchronous `internal/plugin` publication threw.

        `fiber.ts` constructor catch block: `void Promise.resolve(this.dispose()).
        catch(reason => this.ctx.logger.error(reason))`. Disposing removes this
        fiber from the parent's effect list and from the runtime records, so
        neither outlives the failed publication. With a running loop the settle
        awaitable runs on a task; with none it is driven to completion here, the
        port's stand-in for the ambient microtask queue that upstream always has.
        A teardown failure is logged only, so the publication error stays the
        raised one.
        """
        try:
            settled = self.dispose()
        except Exception as reason:
            self._log_error(reason)
            return
        if not inspect.isawaitable(settled):
            return

        async def _settle() -> None:
            try:
                await settled
            except Exception as reason:
                self._log_error(reason)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            run_async_setup_sync(_settle())
            return
        loop.create_task(_settle())

    def _log_error(self, reason: Any) -> None:
        """Report a teardown failure through the fiber logger, never raising."""
        if not self.ctx or not hasattr(self.ctx, "logger"):
            return
        try:
            self.ctx.logger.error(reason)
        except Exception:
            # A logger that throws must not replace the failure being reported.
            pass

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
