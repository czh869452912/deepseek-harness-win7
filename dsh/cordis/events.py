"""
Cordis Event Bus matching reference/vendor/cordis/src/events.ts
Supports emit, parallel, serial, bail, and waterfall dispatch modes with internal/listener interception.
"""

from dsh.cordis.awaiting import resume_coroutine as _resume_listener, await_callback_result
from dsh.cordis.errors import AggregateError as BaseAggregateError, safe_string
import asyncio
import concurrent.futures
import contextvars
import inspect
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union


def is_bailed(value: Any) -> bool:
    """
    Return whether an event result should stop a bail-style dispatch.
    Returns True unless value is None or False.
    """
    return value is not None and value is not False


class AggregateError(BaseAggregateError):
    """Aggregated exception raised by parallel dispatch when listeners fail."""
    def __init__(self, errors: List[Exception]):
        super().__init__(errors)

    def __str__(self) -> str:
        return f"AggregateError ({len(self.errors)} errors):\n" + "\n".join("  - " + safe_string(e) for e in self.errors)


class Hook:
    """Registered listener record stored by the event service."""
    def __init__(self, callback: Callable[..., Any], prepend: bool = False, global_listener: bool = False, ctx: Any = None):
        self.callback = callback
        self.prepend = prepend
        self.global_listener = global_listener
        self.ctx = ctx


def _bind_caller_ctx(cb: Callable[..., Any], caller_ctx: Any) -> Callable[..., Any]:
    if not callable(cb):
        return cb
    try:
        sig = inspect.signature(cb)
        has_caller_ctx = "caller_ctx" in sig.parameters
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        pos_names = [p.name for p in sig.parameters.values() if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        caller_idx = pos_names.index("caller_ctx") if has_caller_ctx and "caller_ctx" in pos_names else None
        if has_caller_ctx or has_varkw:
            import functools
            @functools.wraps(cb)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                if "caller_ctx" not in kwargs and (caller_idx is None or len(args) <= caller_idx):
                    kwargs["caller_ctx"] = caller_ctx
                return cb(*args, **kwargs)
            return wrapped
    except Exception:
        pass
    return cb


_loopless_loop: Optional[asyncio.AbstractEventLoop] = None
_loopless_thread: Optional[threading.Thread] = None
_loopless_guard = threading.Lock()


def _run_loopless_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run the owned loop-less listener loop as the current loop of its thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _loopless_owner() -> asyncio.AbstractEventLoop:
    """
    Return the owned loop that settles listeners dispatched without an ambient loop.

    `events.ts:194-195` invokes every listener and never waits for a returned
    promise, because JavaScript always has a microtask queue that settles it. A
    CPython coroutine advances only while a loop holds it, so the loop-less branch
    of `emit` hands its listener to this loop, which runs on a daemon thread for
    the life of the process.
    """
    global _loopless_loop, _loopless_thread
    with _loopless_guard:
        if _loopless_loop is None or _loopless_loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=_run_loopless_loop, args=(loop,), name="dsh-cordis-events", daemon=True)
            thread.start()
            _loopless_loop = loop
            _loopless_thread = thread
        return _loopless_loop


def _report_loopless_listener_failure(loop: asyncio.AbstractEventLoop, event_name: str, ctx: Any, error: BaseException) -> None:
    """Report a loop-less listener failure to its owner, or to the owned loop when it has no logger."""
    logger = getattr(ctx, "logger", None)
    if callable(logger):
        logger("events").error("Listener for '%s' failed: %s", event_name, error)
        return
    loop.call_exception_handler({"message": "Listener for '%s' failed" % event_name, "exception": error})


class _LooplessDispatchBarrier:
    """
    Dispatch-wide release barrier shared by the loop-less listeners of one `emit`.

    `events.ts:194-195` runs every listener inside a single synchronous
    `this.dispatch('emit', args).map(cb => cb(...args))` and discards the returned
    promises, so no promise continuation can be observed before that whole invocation
    has completed: JavaScript only drains the microtask queue once the dispatch stack
    has unwound. Listeners dispatched without an ambient loop are settled on the owned
    loop, which runs concurrently with the emitter, so every settlement waits on this
    barrier and the emitter releases it after the last listener has been invoked and
    its synchronous prefix has run.
    """

    def __init__(self) -> None:
        self._gate: "concurrent.futures.Future" = concurrent.futures.Future()

    def release(self) -> None:
        """Release the continuations held by this dispatch, once, from the emitter."""
        if not self._gate.done():
            self._gate.set_result(None)

    async def wait(self) -> None:
        """Wait until the emitter has invoked every listener of this dispatch."""
        await asyncio.wrap_future(self._gate, loop=asyncio.get_running_loop())


async def _enter_then_settle(
    result: Any,
    event_name: str,
    ctx: Any,
    entered: threading.Event,
    barrier: _LooplessDispatchBarrier,
) -> None:
    """
    Start one loop-less listener, release its dispatcher, then settle it behind the barrier.

    The listener's synchronous prefix is run by this coroutine through an explicit first
    step, so `entered` marks the moment everything upstream executes inside `cb(...)` is
    done: `emit` invokes the next listener only afterwards, which keeps the listener order
    of the dispatch. The awaited continuation is then held by the dispatch-wide barrier,
    because no listener's continuation may run before the emitter has invoked the last
    listener (events.ts:194-195). `entered` is set on every path. A listener failure is
    reported before this settlement completes, so a caller that joins it observes the
    report.
    """
    if not inspect.iscoroutine(result):
        # A generic awaitable cannot be stepped by hand: it has no synchronous prefix left
        # to run, so it is only awaited once the dispatch released the barrier.
        entered.set()
        await barrier.wait()
        try:
            await result
        except Exception as exc:
            _report_loopless_listener_failure(asyncio.get_running_loop(), event_name, ctx, exc)
        return
    try:
        awaited = result.send(None)
    except StopIteration:
        # The body finished without suspending, like a listener that returns at once.
        return
    except Exception as exc:
        _report_loopless_listener_failure(asyncio.get_running_loop(), event_name, ctx, exc)
        return
    finally:
        entered.set()
    await _drive_loopless_settlement(result, awaited, event_name, ctx, barrier)


async def _drive_loopless_settlement(
    listener: Any,
    awaited: Any,
    event_name: str,
    ctx: Any,
    barrier: _LooplessDispatchBarrier,
) -> None:
    """
    Drive a loop-less listener past its synchronous prefix inside this settlement.

    Awaiting the listener as an independent task would let its continuation run while the
    emitter is still invoking later listeners, so each suspension is awaited here and then
    resumed explicitly: the continuation stays with this settlement, which first waits on the
    dispatch-wide `barrier`, so nothing resumes before the emitter has invoked the last
    listener of the dispatch. Awaiting a suspension this way needs the same bookkeeping a task
    performs, and a failure - including cancellation of the settlement - is delivered into the
    listener at its suspension point, exactly as it is for a task, so its cleanup still runs.
    A failing listener body is reported here, which is the only handling it gets, exactly as
    the in-loop branch leaves the failure with its scheduled task.
    """
    loop = asyncio.get_running_loop()
    held = False
    while True:
        failure: Optional[BaseException] = None
        value: Any = None
        try:
            if not held:
                try:
                    await barrier.wait()
                except BaseException as exc:
                    failure = exc
                held = True
            if failure is None:
                if awaited is None:
                    # A bare `yield`, as produced by `asyncio.sleep(0)`, only reschedules.
                    await asyncio.sleep(0)
                elif isinstance(awaited, asyncio.Future):
                    # The listener's `await` yielded this future to the dispatch instead of to
                    # a task, so the blocking marker that a consumer clears on receipt is still
                    # set: clear it and wait for the future here, as `Task.__step` does
                    # (asyncio/tasks.py:314), instead of awaiting it with the marker still set.
                    awaited._asyncio_future_blocking = False
                    value = await awaited
                else:
                    value = await awaited
        except BaseException as exc:
            failure = exc
        try:
            awaited = listener.throw(failure) if failure is not None else listener.send(value)
        except StopIteration:
            return
        except Exception as exc:
            _report_loopless_listener_failure(loop, event_name, ctx, exc)
            return



def _release_loopless_barrier(barrier: "_LooplessDispatchBarrier") -> None:
    """
    Ask the owned loop to release the finished dispatch's held continuations.

    The release is published to the loop that owns the settlements instead of being
    performed by the emitter, so the loop drains the continuations after the emitter's
    synchronous dispatch frame has completed: upstream drains its promise continuations
    only once the dispatch stack has unwound (events.ts:194-195).
    """
    loop = _loopless_owner()
    try:
        loop.call_soon_threadsafe(barrier.release)
    except RuntimeError:
        # The owned loop is closing, so release inline rather than hold the continuations.
        barrier.release()


def _normalize_event_call(event_name: Any, args: Sequence[Any], default_caller: Any, kwargs: Dict[str, Any]) -> Tuple[str, List[Any], Any]:
    caller_ctx = kwargs.pop("caller_ctx", None)
    if not isinstance(event_name, str) and args and isinstance(args[0], str):
        caller_ctx = event_name
        actual_event_name = args[0]
        actual_args = list(args[1:])
    else:
        actual_event_name = str(event_name)
        actual_args = list(args)
    if caller_ctx is None:
        caller_ctx = default_caller
    return actual_event_name, actual_args, caller_ctx


class EventBus:
    """
    Cordis Event Bus supporting emit, waterfall, parallel, serial, and bail dispatch modes
    with context filtering, internal/listener interception, and 1:1 bail semantics.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._hooks: Dict[str, List[Hook]] = {}
        self._loopless_settlements: Set[Any] = set()
        self._emit_settlements: Set[Any] = set()

        # 1:1 Built-in internal/listener handler matching TS EventsService
        def _on_internal_listener(name: str, listener: Any, options: Any = None, *args: Any, **kwargs: Any) -> Any:
            if isinstance(options, dict):
                prepend = bool(options.get("prepend", False))
                is_global = bool(options.get("global", False))
            elif isinstance(options, bool):
                prepend = options
                is_global = bool(args[0]) if args else False
            else:
                prepend = False
                is_global = False
            if is_global:
                return None
            target_ctx = kwargs.get("caller_ctx") or (args[1] if len(args) > 1 and hasattr(args[1], "fiber") else None) or (args[0] if args and hasattr(args[0], "fiber") else None) or self.ctx
            if name == "internal/update" and target_ctx and hasattr(target_ctx, "fiber") and target_ctx.fiber:
                fiber = target_ctx.fiber
                if "internal/update" not in fiber._hooks:
                    from dsh.cordis.utils import DisposableList
                    fiber._hooks["internal/update"] = DisposableList()
                hooks = fiber._hooks["internal/update"]
                if prepend:
                    return hooks.unshift(listener)
                return hooks.push(listener)
            return None

        self.on("internal/listener", _on_internal_listener, global_listener=True)

        def _on_internal_update(config: Any, no_save: bool = False, *args: Any, **kwargs: Any) -> Any:
            target_ctx = kwargs.get("caller_ctx") or self.ctx
            fiber = getattr(target_ctx, "fiber", None) if target_ctx else None
            cbs = list(getattr(fiber, "_hooks", {}).get("internal/update", [])) if fiber else []

            next_callback = args[-1] if args and callable(args[-1]) else None

            def _next(cfg=config, ns=no_save):
                if cbs:
                    cb = cbs.pop(0)
                    return cb(cfg, ns, _next)
                elif next_callback and callable(next_callback):
                    try:
                        sig = inspect.signature(next_callback)
                        params = list(sig.parameters.values())
                        has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                        if has_var or len(params) >= 3:
                            return next_callback(cfg, ns, _next)
                        elif len(params) == 2:
                            return next_callback(cfg, ns)
                        elif len(params) == 1:
                            return next_callback(cfg)
                        else:
                            return next_callback()
                    except (ValueError, TypeError):
                        try:
                            return next_callback(cfg, ns, _next)
                        except TypeError:
                            return next_callback(cfg)
                return cfg

            return _next()

        self.on("internal/update", _on_internal_update, global_listener=True, prepend=True)

    def on(
        self,
        event_name: str,
        handler: Callable[..., Any],
        prepend: bool = False,
        global_listener: bool = False,
        ctx: Any = None
    ) -> Callable[[], None]:
        """
        Register an event handler. Returns a disposer function to unregister.
        """
        caller_ctx = ctx or self.ctx

        # 1:1 Assert Active matching TS events.ts:293
        if caller_ctx is not None and hasattr(caller_ctx, "fiber") and caller_ctx.fiber is not None:
            caller_ctx.fiber.assert_active()

        # 1:1 Reflect Bind matching TS events.ts:295
        if caller_ctx is not None and hasattr(caller_ctx, "reflect") and hasattr(caller_ctx.reflect, "bind"):
            handler = caller_ctx.reflect.bind(handler)

        # Handle internal/listener interception hook matching TS events.ts:296
        options = {"prepend": prepend, "global": global_listener}
        intercepted = self.bail("internal/listener", event_name, handler, options, caller_ctx=caller_ctx or self.ctx)
        if intercepted:
            if callable(intercepted):
                return intercepted
            return lambda: True

        hook = Hook(handler, prepend=prepend, global_listener=global_listener, ctx=caller_ctx)

        def setup():
            if event_name not in self._hooks:
                self._hooks[event_name] = []
            if prepend:
                self._hooks[event_name].insert(0, hook)
            else:
                self._hooks[event_name].append(hook)
            return disposer

        def disposer() -> bool:
            if event_name in self._hooks and hook in self._hooks[event_name]:
                self._hooks[event_name].remove(hook)
                return True
            return False

        label = f'ctx.on("{event_name}")'
        if caller_ctx is not None and hasattr(caller_ctx, "fiber") and caller_ctx.fiber is not None:
            return caller_ctx.fiber.effect(setup, label=label)
        else:
            setup()
            return disposer

    def once(
        self,
        event_name: str,
        handler: Callable[..., Any],
        prepend: bool = False,
        global_listener: bool = False,
        ctx: Any = None
    ) -> Callable[[], None]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            disposer()
            try:
                sig = inspect.signature(handler)
                if "caller_ctx" not in sig.parameters and not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    kwargs.pop("caller_ctx", None)
            except Exception:
                pass
            return handler(*args, **kwargs)

        disposer = self.on(event_name, wrapper, prepend=prepend, global_listener=global_listener, ctx=ctx)
        return disposer

    def _dispatch_hooks(
        self,
        dispatch_type: str,
        event_name: str,
        args_or_ctx: Any = None,
        caller_ctx: Any = None,
    ) -> List[Callable[..., Any]]:
        actual_args: List[Any] = []
        actual_ctx = caller_ctx

        if actual_ctx is None:
            if hasattr(args_or_ctx, "registry") and hasattr(args_or_ctx, "reflect"):
                actual_ctx = args_or_ctx
                actual_args = []
            elif isinstance(args_or_ctx, (list, tuple)):
                actual_args = list(args_or_ctx)
            elif args_or_ctx is not None:
                actual_args = [args_or_ctx]
        else:
            if isinstance(args_or_ctx, (list, tuple)):
                actual_args = list(args_or_ctx)
            elif args_or_ctx is not None:
                actual_args = [args_or_ctx]

        if not event_name.startswith("internal/"):
            # Fired for non-internal events to diagnose dispatches (mode, name, args, caller_ctx)
            self.emit("internal/dispatch", dispatch_type, event_name, actual_args, actual_ctx)

        hooks = list(self._hooks.get(event_name, []))
        result_callbacks = []
        for hook in hooks:
            cb = hook.callback
            if hook.global_listener:
                if actual_ctx is not None:
                    cb = _bind_caller_ctx(cb, actual_ctx)
                result_callbacks.append(cb)
            else:
                if actual_ctx is not None and getattr(actual_ctx, "__cordis_context_brand__", None) == "cordis.v1.context":
                    ctx_filter = getattr(actual_ctx, "_filter_hook", None) or getattr(actual_ctx, "__dict__", {}).get("filter")
                else:
                    ctx_filter = getattr(actual_ctx, "filter", None)
                if ctx_filter is None and callable(actual_ctx):
                    ctx_filter = actual_ctx
                if ctx_filter is None:
                    if actual_ctx is not None:
                        cb = _bind_caller_ctx(cb, actual_ctx)
                    result_callbacks.append(cb)
                elif callable(ctx_filter):
                    if ctx_filter(hook.ctx):
                        if actual_ctx is not None:
                            cb = _bind_caller_ctx(cb, actual_ctx)
                        result_callbacks.append(cb)
        return result_callbacks

    def dispatch(self, dispatch_type: str, args: Sequence[Any]) -> List[Callable[..., Any]]:
        """
        1:1 TS EventBus.dispatch(type, args) matching TS events.ts.
        args can be [event_name, *event_args] or [carrier, event_name, *event_args].
        """
        if not args:
            return []
        if isinstance(args[0], str):
            event_name = args[0]
            event_args = list(args[1:])
            caller_ctx = None
        else:
            caller_ctx = args[0]
            event_name = args[1]
            event_args = list(args[2:])
        return self._dispatch_hooks(dispatch_type, event_name, event_args, caller_ctx)

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Dispatch an event synchronously, ignoring return values matching TS EventBus.emit.

        A listener that returns an awaitable is scheduled on the running loop, or owned by
        `_settle_loopless_listener` when the dispatching caller holds no loop; `emit` returns
        without waiting for that settlement either way (events.ts:194-196). The loop-less
        listeners of one dispatch share a `_LooplessDispatchBarrier`, released once the last
        listener has been invoked, so no continuation can overtake a later listener.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
        barrier: Optional[_LooplessDispatchBarrier] = None
        try:
            for listener in listeners:
                sig = None
                try:
                    sig = inspect.signature(listener)
                except Exception:
                    pass

                res = listener(*actual_args, **kwargs)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        self._start_emit_listener(res, loop, event_name)
                    except RuntimeError:
                        if barrier is None:
                            barrier = _LooplessDispatchBarrier()
                        self._settle_loopless_listener(res, event_name, caller_ctx or self.ctx, barrier)
        finally:
            # The synchronous dispatch is over, so every listener has been invoked and every
            # prefix has run: the continuations held behind the barrier may resume, and none
            # is left behind when a listener raised out of the dispatch.
            if barrier is not None:
                _release_loopless_barrier(barrier)

    def _start_emit_listener(self, result: Any, loop: Any, event_name: str) -> None:
        """Run an async listener's prefix now; retain and report its tail once."""
        context = contextvars.copy_context()
        if inspect.iscoroutine(result):
            try:
                awaited = context.run(result.send, None)
            except StopIteration:
                return
            except BaseException as exc:
                # An async body throws into its Promise, not out of emit. The
                # synchronous listener path above still propagates immediately.
                future = loop.create_future()
                future.set_exception(exc)
                task = future
            else:
                task = context.run(loop.create_task, _resume_listener(result, awaited))
        else:
            task = asyncio.ensure_future(result)
        self._emit_settlements.add(task)

        def completed(done):
            self._emit_settlements.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                loop.call_exception_handler({
                    "message": "Listener for '%s' failed" % event_name,
                    "exception": error, "future": done,
                })
        task.add_done_callback(completed)

    def _settle_loopless_listener(
        self,
        result: Any,
        event_name: str,
        ctx: Any,
        barrier: _LooplessDispatchBarrier,
    ) -> None:
        """
        Hand a listener's returned awaitable to the owned loop and return once its body starts.

        Upstream `emit` returns without waiting for a listener's returned promise, so the
        settlement is owned instead of awaited: it stays registered until it finishes,
        `join_loopless_settlements` can wait for it, and the awaitable is never collected
        unawaited. The listener's synchronous prefix still runs on the owned loop thread
        before this returns, matching the reference, so that prefix must not block on the
        dispatching thread. The settlement's continuation then waits on the dispatch-wide
        `barrier`, which the emitter releases only after the last listener of this dispatch
        has been invoked and its prefix has run (events.ts:194-195).
        """
        loop = _loopless_owner()
        entered = threading.Event()
        settlement = asyncio.run_coroutine_threadsafe(_enter_then_settle(result, event_name, ctx, entered, barrier), loop)
        self._loopless_settlements.add(settlement)
        settlement.add_done_callback(lambda done: self._retire_loopless_settlement(done, loop, event_name, ctx))
        entered.wait()

    def _retire_loopless_settlement(self, settlement: Any, loop: asyncio.AbstractEventLoop, event_name: str, ctx: Any) -> None:
        """Drop a finished settlement and report a failure that did not come from the listener body."""
        self._loopless_settlements.discard(settlement)
        if settlement.cancelled():
            return
        error = settlement.exception()
        if error is not None:
            _report_loopless_listener_failure(loop, event_name, ctx, error)

    def pending_loopless_settlements(self) -> int:
        """
        Count this bus's listeners whose dispatch had no ambient loop and have not settled yet.

        @returns the number of unsettled loop-less settlements.
        """
        return sum(1 for settlement in list(self._loopless_settlements) if not settlement.done())

    def join_loopless_settlements(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for this bus's listeners dispatched without an ambient loop to settle.

        @param timeout seconds to wait for all of them; `None` waits as long as it takes.
        @returns `True` when no settlement remains pending.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            pending = [settlement for settlement in list(self._loopless_settlements) if not settlement.done()]
            if not pending:
                return True
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            concurrent.futures.wait(pending, timeout=remaining)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event asynchronously to listeners in sequence.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
        for listener in listeners:
            res = listener(*actual_args, **kwargs)
            if inspect.isawaitable(res):
                await res

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Parallel dispatch: run all listeners concurrently matching TS EventBus.parallel.
        Resolves with no value; raises AggregateError if any listeners fail.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
        if not listeners:
            return None

        async def _run(cb: Callable[..., Any]) -> Any:
            res = cb(*actual_args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res

        results = await asyncio.gather(*[_run(cb) for cb in listeners], return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise AggregateError(errors)
        return None

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, awaiting listeners in order until one bails.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("serial", event_name, actual_args, caller_ctx)
        for listener in listeners:
            res = listener(*actual_args, **kwargs)
            res = await await_callback_result(res)
            if is_bailed(res):
                return res
        return None

    def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event synchronously, stopping on the first bail value matching TS EventBus.bail.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("bail", event_name, actual_args, caller_ctx)
        for listener in listeners:
            sig = None
            try:
                sig = inspect.signature(listener)
            except Exception:
                pass
            if sig is not None:
                params = list(sig.parameters.values())
                has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
                call_args = actual_args if (has_var or pos_count >= len(actual_args)) else actual_args[:pos_count]
                if event_name == "internal/listener" and len(actual_args) == 3 and isinstance(actual_args[2], dict) and not has_var and pos_count == 4:
                    call_args = (actual_args[0], actual_args[1], actual_args[2].get("prepend", False), actual_args[2].get("global", False))
                res = listener(*call_args, **kwargs)
            else:
                res = listener(*actual_args, **kwargs)
            if is_bailed(res):
                return res
        return None

    bail_sync = bail

    def waterfall_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Synchronous waterfall middleware pipeline matching TS waterfall semantics.
        Supports onion middleware return-threading and short-circuit veto.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = list(self._dispatch_hooks("waterfall", event_name, list(actual_args), caller_ctx))
        args_list = list(actual_args)
        inner = args_list.pop() if args_list and callable(args_list[-1]) else None

        idx = 0
        def next_fn(*override_args: Any) -> Any:
            nonlocal idx
            current_args = list(args_list)
            if idx < len(listeners):
                cb = listeners[idx]
                idx += 1
                sig = None
                try:
                    sig = inspect.signature(cb)
                except Exception:
                    pass
                takes_next = False
                pos_count = len(current_args)
                if sig is not None:
                    param_names = list(sig.parameters.keys())
                    params = list(sig.parameters.values())
                    has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    takes_next = "next" in param_names or "next_fn" in param_names or has_var or len(params) >= len(current_args) + 1
                    pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))

                if takes_next:
                    call_args = list(current_args) + [next_fn]
                    return cb(*call_args, **kwargs)
                elif pos_count == 0:
                    return cb()
                else:
                    call_args = current_args[:pos_count] if pos_count < len(current_args) else current_args
                    return cb(*call_args, **kwargs)
            elif inner is not None:
                sig = None
                try:
                    sig = inspect.signature(inner)
                except Exception:
                    pass
                takes_next = False
                pos_count = len(current_args)
                if sig is not None:
                    param_names = list(sig.parameters.keys())
                    params = list(sig.parameters.values())
                    has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    takes_next = "next" in param_names or "next_fn" in param_names or has_var or len(params) >= len(current_args) + 1
                    pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))

                call_args = (list(current_args) + [next_fn]) if takes_next else (current_args[:pos_count] if pos_count < len(current_args) else current_args)
                return inner(*call_args)
            else:
                return current_args[0] if current_args else None

        return next_fn()

    async def waterfall(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline matching TS waterfall semantics.
        Supports onion middleware return-threading and short-circuit veto.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = list(self._dispatch_hooks("waterfall", event_name, list(actual_args), caller_ctx))
        args_list = list(actual_args)
        inner = args_list.pop() if args_list and callable(args_list[-1]) else None

        idx = 0
        async def next_fn(*override_args: Any) -> Any:
            nonlocal idx
            current_args = list(args_list)
            if idx < len(listeners):
                cb = listeners[idx]
                idx += 1
                sig = None
                try:
                    sig = inspect.signature(cb)
                except Exception:
                    pass
                takes_next = False
                pos_count = len(current_args)
                if sig is not None:
                    param_names = list(sig.parameters.keys())
                    params = list(sig.parameters.values())
                    has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    takes_next = "next" in param_names or "next_fn" in param_names or has_var or len(params) >= len(current_args) + 1
                    pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))

                if takes_next:
                    call_args = list(current_args) + [next_fn]
                    res = cb(*call_args, **kwargs)
                    if inspect.isawaitable(res):
                        res = await res
                    return res
                elif pos_count == 0:
                    res = cb()
                    if inspect.isawaitable(res):
                        res = await res
                    return res
                else:
                    call_args = current_args[:pos_count] if pos_count < len(current_args) else current_args
                    res = cb(*call_args, **kwargs)
                    if inspect.isawaitable(res):
                        res = await res
                    return res
            elif inner is not None:
                sig = None
                try:
                    sig = inspect.signature(inner)
                except Exception:
                    pass
                takes_next = False
                pos_count = len(current_args)
                if sig is not None:
                    param_names = list(sig.parameters.keys())
                    params = list(sig.parameters.values())
                    has_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    takes_next = "next" in param_names or "next_fn" in param_names or has_var or len(params) >= len(current_args) + 1
                    pos_count = sum(1 for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))

                call_args = (list(current_args) + [next_fn]) if takes_next else (current_args[:pos_count] if pos_count < len(current_args) else current_args)
                res = inner(*call_args)
                if inspect.isawaitable(res):
                    res = await res
                return res
            else:
                return current_args[0] if current_args else None

        return await next_fn()
