"""
Cordis Timer Service matching reference/vendor/timer/src/index.ts
Disposable timer helpers mixed into Cordis contexts.
"""

import asyncio
import inspect
import threading
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union

from dsh.cordis.service import Service


class _AsyncIntervalIterator:
    """Async iterator for interval ticks matching TS TimerService.interval."""

    def __init__(self, service: "TimerService", delay_ms: float, target_ctx: Optional[Any] = None):
        self.service = service
        self.ctx = target_ctx or service.ctx
        self.delay_sec = max(0.001, delay_ms / 1000.0)
        self._done: Optional[Dict[str, Any]] = None
        self._next_future: Optional[asyncio.Future] = None
        self._task: Optional[asyncio.Task] = None
        self._created_at: Optional[float] = None

        def _setup():
            self._created_at = time.monotonic()
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._tick_loop(self.delay_sec))
            except RuntimeError:
                # setInterval needs no event loop. The tick loop is a task, so a
                # caller created outside one starts it at its first wait, offset
                # to the phase that began at creation.
                self._task = None

            def _cleanup():
                if self._task and not self._task.done():
                    self._task.cancel()
                if self._done is not None:
                    return
                err = RuntimeError("Context has been disposed")
                self._done = {"kind": "throw", "reason": err}
                if self._next_future is not None and not self._next_future.done():
                    self._next_future.set_exception(err)
                    self._next_future = None

            return _cleanup

        self._dispose = self.ctx.effect(_setup, "ctx.interval()")

    async def _tick_loop(self, first_delay_sec: float) -> None:
        """Deliver one tick per `delay_sec`, the first `first_delay_sec` from now."""
        try:
            await asyncio.sleep(first_delay_sec)
            while not self._done:
                if self._next_future is not None and not self._next_future.done():
                    self._next_future.set_result(None)
                    self._next_future = None
                await asyncio.sleep(self.delay_sec)
        except asyncio.CancelledError:
            pass

    def _first_tick_delay(self) -> float:
        """Delay to the next tick of the cadence that started at creation."""
        if self._created_at is None:
            return self.delay_sec
        return self.delay_sec - ((time.monotonic() - self._created_at) % self.delay_sec)

    def __aiter__(self) -> AsyncIterator[None]:
        return self

    @property
    def _disposed(self) -> bool:
        return self._done is not None

    async def __anext__(self) -> None:
        if self._done is not None:
            if self._done["kind"] == "return":
                # TS `next()` resolves `{ done: true, value }` and keeps returning it.
                raise StopAsyncIteration(self._done.get("value"))
            raise self._done["reason"]

        loop = asyncio.get_running_loop()
        if self._task is None:
            self._task = loop.create_task(self._tick_loop(self._first_tick_delay()))
        fut = loop.create_future()
        self._next_future = fut
        try:
            await fut
        finally:
            if self._next_future is fut:
                self._next_future = None

    async def aclose(self, value: Any = None) -> None:
        if not self._done:
            self._done = {"kind": "return", "value": value}
            if self._next_future is not None and not self._next_future.done():
                # TS resolves the pending `next()` with `{ done: true, value }`.
                self._next_future.set_exception(StopAsyncIteration(value))
                self._next_future = None
            if callable(self._dispose):
                self._dispose()

    async def athrow(self, reason: Any) -> None:
        """
        Throw `reason` into the iterator matching TS `throw(reason)`.

        The reference resolves `{ done: true, value: undefined }`; a finished
        Python async iterator signals that by raising StopAsyncIteration.
        """
        if not self._done:
            self._done = {"kind": "throw", "reason": reason}
            if self._next_future is not None and not self._next_future.done():
                exc = reason if isinstance(reason, Exception) else RuntimeError(str(reason))
                self._next_future.set_exception(exc)
                self._next_future = None
            if callable(self._dispose):
                self._dispose()
        raise StopAsyncIteration

    def __del__(self) -> None:
        if not self._done:
            self._done = {"kind": "return", "value": None}
            try:
                if self._task and not self._task.done():
                    self._task.cancel()
            except Exception:
                pass
            if callable(self._dispose):
                try:
                    self._dispose()
                except Exception:
                    pass


class TimerService(Service):
    """
    Disposable timer helpers mixed into Cordis contexts.
    Matching reference/vendor/timer/src/index.ts.
    """

    name = "timer"

    def __init__(self, ctx: Any):
        super().__init__(ctx, "timer")
        if hasattr(ctx, "mixin"):
            ctx.mixin("timer", ["timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"])

    def setTimeout(self, callback: Callable[[], Any], delay_ms: float, ctx: Optional[Any] = None) -> Callable[[], None]:
        """Deprecated alias for ctx.timeout(callback, delay_ms)."""
        return self.timeout(callback, delay_ms, ctx=ctx)

    def setInterval(self, callback: Callable[[], Any], delay_ms: float, ctx: Optional[Any] = None) -> Callable[[], None]:
        """Deprecated alias for ctx.interval(callback, delay_ms)."""
        return self.interval(callback, delay_ms, ctx=ctx)

    def timeout(
        self,
        callback_or_delay: Union[Callable[[], Any], float, int],
        delay_ms: Optional[Union[float, int]] = None,
        ctx: Optional[Any] = None
    ) -> Any:
        """
        Run a callback once, or return an awaitable that resolves after delay_ms.

        The owning fiber's disposal before the deadline rejects the awaitable with
        `RuntimeError("Context has been disposed")`, and a later await still raises;
        a disposal after the deadline leaves an already-resolved awaitable resolved.
        All timers are automatically cancelled when owning fiber/context is disposed.
        """
        target_ctx = ctx or self.ctx

        if callable(callback_or_delay):
            callback = callback_or_delay
            delay = float(delay_ms if delay_ms is not None else 0)
            delay_sec = max(0.0, delay / 1000.0)

            # The reference reaches this callback only from the runtime timer
            # queue, so the effect that owns the timer and its disposer always
            # exist before the callback body runs. The no-loop fallback fires on
            # its own thread, which must wait for that registration first.
            registered = threading.Event()
            registered_dispose: List[Callable[[], None]] = []

            def _setup():
                timer_handle: Optional[asyncio.TimerHandle] = None
                threading_timer: Optional[threading.Timer] = None
                disposed = False

                def _on_timeout():
                    nonlocal disposed
                    registered.wait()
                    if disposed:
                        return
                    disposed = True
                    if registered_dispose:
                        registered_dispose[0]()
                    # The reference calls the callback unguarded (index.ts:38), so a
                    # raising callback escapes to the runtime's uncaught-exception
                    # handling instead of being caught here.
                    res = callback()
                    if inspect.isawaitable(res):
                        try:
                            res_loop = asyncio.get_running_loop()
                            res_loop.create_task(res)
                        except RuntimeError:
                            pass

                try:
                    loop = asyncio.get_running_loop()
                    timer_handle = loop.call_later(delay_sec, _on_timeout)
                except RuntimeError:
                    threading_timer = threading.Timer(delay_sec, _on_timeout)
                    threading_timer.daemon = True
                    threading_timer.start()

                def _cleanup():
                    nonlocal disposed
                    disposed = True
                    if timer_handle is not None:
                        timer_handle.cancel()
                    if threading_timer is not None:
                        threading_timer.cancel()

                return _cleanup

            # `_setup` may already have armed the fallback thread, so the
            # registration gate is released however `effect` returns.
            dispose: Callable[[], None] = lambda: None
            try:
                dispose = target_ctx.effect(_setup, "ctx.timeout()")
            finally:
                registered_dispose.append(dispose)
                registered.set()
            return dispose
        else:
            delay = float(callback_or_delay)
            delay_sec = max(0.0, delay / 1000.0)

            try:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
            except RuntimeError:
                loop = None
                future = None

            if future is None:
                # No loop can hold the timer, so the deadline is fixed here and the
                # returned coroutine waits out whatever is left of it. The reference
                # rejects the promise from its disposer while the deadline has not
                # elapsed (index.ts:47-51), so the rejection is recorded here and the
                # coroutine raises it at the consumer's first checkpoint, whether that
                # checkpoint comes after the deadline or is already suspended.
                deadline = time.monotonic() + delay_sec
                rejected = False
                waiter: Optional[asyncio.Future] = None
                waiter_loop: Optional[asyncio.AbstractEventLoop] = None

                def _resolve_no_loop() -> None:
                    if waiter is not None and not waiter.done():
                        waiter.set_result(None)

                def _reject_no_loop() -> None:
                    if waiter is not None and not waiter.done():
                        waiter.set_exception(RuntimeError("Context has been disposed"))

                def _setup_no_loop():
                    def _cleanup_no_loop():
                        nonlocal rejected
                        # `clearTimeout` is a no-op once the timer fired, so only a
                        # disposal before the deadline rejects the promise.
                        rejected = time.monotonic() < deadline
                        if not rejected or waiter_loop is None:
                            return
                        try:
                            running = asyncio.get_running_loop()
                        except RuntimeError:
                            running = None
                        if running is waiter_loop:
                            _reject_no_loop()
                        else:
                            # The consumer awaits on a loop this disposer does not run
                            # on, so the rejection is handed to that loop.
                            waiter_loop.call_soon_threadsafe(_reject_no_loop)
                    return _cleanup_no_loop

                dispose = target_ctx.effect(_setup_no_loop, "ctx.timeout()")

                async def _fallback_sleep():
                    nonlocal waiter, waiter_loop
                    handle: Optional[asyncio.TimerHandle] = None
                    try:
                        if rejected:
                            raise RuntimeError("Context has been disposed")
                        waiter_loop = asyncio.get_running_loop()
                        if rejected:
                            raise RuntimeError("Context has been disposed")
                        waiter = waiter_loop.create_future()
                        handle = waiter_loop.call_later(max(0.0, deadline - time.monotonic()), _resolve_no_loop)
                        await waiter
                    finally:
                        if handle is not None:
                            handle.cancel()
                        waiter = None
                        waiter_loop = None
                        dispose()

                return _fallback_sleep()

            def _setup():
                timer_handle: Optional[asyncio.TimerHandle] = None

                def _resolve():
                    if not future.done():
                        future.set_result(None)

                timer_handle = loop.call_later(delay_sec, _resolve)

                def _cleanup():
                    if timer_handle is not None:
                        timer_handle.cancel()
                    if not future.done():
                        future.set_exception(RuntimeError("Context has been disposed"))

                return _cleanup

            dispose = target_ctx.effect(_setup, "ctx.timeout()")
            future.add_done_callback(lambda _f: dispose())

            async def _wait_future():
                try:
                    return await future
                finally:
                    dispose()

            return _wait_future()

    def interval(
        self,
        callback_or_delay: Union[Callable[[], Any], float, int],
        delay_ms: Optional[Union[float, int]] = None,
        ctx: Optional[Any] = None
    ) -> Any:
        """
        Run a callback repeatedly, or return an async iterator of ticks.
        Automatically disposed with context.
        """
        target_ctx = ctx or self.ctx

        if callable(callback_or_delay):
            callback = callback_or_delay
            delay = float(delay_ms if delay_ms is not None else 0)
            delay_sec = max(0.001, delay / 1000.0)

            def _setup():
                disposed = False
                handle: Optional[asyncio.TimerHandle] = None
                threading_timer: Optional[threading.Timer] = None

                def _tick_callback():
                    # The reference hands the callback to the runtime's interval timer
                    # unguarded (index.ts:64), so nothing catches a raising callback
                    # here: it escapes to the runtime's uncaught-exception handling.
                    res = callback()
                    if inspect.isawaitable(res):
                        try:
                            res_loop = asyncio.get_running_loop()
                            res_loop.create_task(res)
                        except RuntimeError:
                            pass

                def _cleanup():
                    nonlocal disposed
                    disposed = True
                    if handle is not None:
                        handle.cancel()
                    if threading_timer is not None:
                        threading_timer.cancel()

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No loop can hold the interval, so its cadence is carried by a
                    # chain of runtime timers rather than by a sleeping worker: every
                    # tick arms its successor, which is what keeps the reference's
                    # `setInterval` firing past a raising callback.
                    def _tick_thread():
                        nonlocal threading_timer
                        if disposed:
                            return
                        threading_timer = threading.Timer(delay_sec, _tick_thread)
                        threading_timer.daemon = True
                        threading_timer.start()
                        if disposed:
                            # A concurrent disposer cleared the interval between the
                            # check above and this arm, so the successor is cleared too.
                            threading_timer.cancel()
                        _tick_callback()

                    threading_timer = threading.Timer(delay_sec, _tick_thread)
                    threading_timer.daemon = True
                    threading_timer.start()
                else:
                    def _tick():
                        nonlocal handle
                        if disposed:
                            return
                        # The reference clears its interval only through the returned
                        # disposer (index.ts:64-65), so the successor tick is armed
                        # before the callback runs: a raising callback cannot end the
                        # chain, and it reaches loop.call_exception_handler instead.
                        handle = loop.call_later(delay_sec, _tick)
                        if disposed:
                            handle.cancel()
                        _tick_callback()

                    handle = loop.call_later(delay_sec, _tick)

                return _cleanup

            return target_ctx.effect(_setup, "ctx.interval()")
        else:
            delay = float(callback_or_delay)
            return _AsyncIntervalIterator(self, delay, target_ctx=target_ctx)

    def throttle(
        self,
        callback: Callable[..., Any],
        delay_ms: float,
        no_trailing: bool = False,
        ctx: Optional[Any] = None
    ) -> Callable[..., Any]:
        """Return a throttled function whose timer is disposed with current fiber."""
        target_ctx = ctx or self.ctx
        delay_sec = max(0.0, delay_ms / 1000.0)
        last_call = -float("inf")
        timer_handle: Optional[asyncio.TimerHandle] = None
        threading_timer: Optional[threading.Timer] = None
        disposed = False

        def _setup():
            def _cleanup():
                nonlocal disposed, timer_handle, threading_timer
                disposed = True
                if timer_handle is not None:
                    timer_handle.cancel()
                    timer_handle = None
                if threading_timer is not None:
                    threading_timer.cancel()
                    threading_timer = None
            return _cleanup

        disposer = target_ctx.effect(_setup, "ctx.throttle()")

        def throttled(*args: Any, **kwargs: Any) -> Any:
            nonlocal last_call, timer_handle, threading_timer
            now = time.time()
            remaining = delay_sec - (now - last_call)

            def _execute(*a, **kw):
                nonlocal last_call, timer_handle, threading_timer
                last_call = time.time()
                timer_handle = None
                threading_timer = None
                res = callback(*a, **kw)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass

            if remaining <= 0:
                if timer_handle is not None:
                    timer_handle.cancel()
                    timer_handle = None
                if threading_timer is not None:
                    threading_timer.cancel()
                    threading_timer = None
                _execute(*args, **kwargs)
            elif not no_trailing and not disposed:
                if timer_handle is not None:
                    timer_handle.cancel()
                if threading_timer is not None:
                    threading_timer.cancel()
                try:
                    loop = asyncio.get_running_loop()
                    timer_handle = loop.call_later(remaining, lambda a=args, kw=kwargs: _execute(*a, **kw))
                except RuntimeError:
                    threading_timer = threading.Timer(remaining, lambda a=args, kw=kwargs: _execute(*a, **kw))
                    threading_timer.daemon = True
                    threading_timer.start()

        throttled.dispose = disposer
        return throttled

    def debounce(
        self,
        callback: Callable[..., Any],
        delay_ms: float,
        ctx: Optional[Any] = None
    ) -> Callable[..., Any]:
        """Return a debounced function whose timer is disposed with current fiber."""
        target_ctx = ctx or self.ctx
        delay_sec = max(0.0, delay_ms / 1000.0)
        timer_handle: Optional[asyncio.TimerHandle] = None
        threading_timer: Optional[threading.Timer] = None
        disposed = False

        def _setup():
            def _cleanup():
                nonlocal disposed, timer_handle, threading_timer
                disposed = True
                if timer_handle is not None:
                    timer_handle.cancel()
                    timer_handle = None
                if threading_timer is not None:
                    threading_timer.cancel()
                    threading_timer = None
            return _cleanup

        disposer = target_ctx.effect(_setup, "ctx.debounce()")

        def debounced(*args: Any, **kwargs: Any) -> Any:
            nonlocal timer_handle, threading_timer
            if disposed:
                return None
            if timer_handle is not None:
                timer_handle.cancel()
                timer_handle = None
            if threading_timer is not None:
                threading_timer.cancel()
                threading_timer = None

            def _execute(*a, **kw):
                nonlocal timer_handle, threading_timer
                timer_handle = None
                threading_timer = None
                if not disposed:
                    res = callback(*a, **kw)
                    if inspect.isawaitable(res):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(res)
                        except RuntimeError:
                            pass

            try:
                loop = asyncio.get_running_loop()
                timer_handle = loop.call_later(delay_sec, lambda a=args, kw=kwargs: _execute(*a, **kw))
            except RuntimeError:
                threading_timer = threading.Timer(delay_sec, lambda a=args, kw=kwargs: _execute(*a, **kw))
                threading_timer.daemon = True
                threading_timer.start()

        debounced.dispose = disposer
        return debounced


Timer = TimerService
