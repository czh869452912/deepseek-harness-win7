"""
Cordis Timer Service matching reference/vendor/timer/src/index.ts
Disposable timer helpers mixed into Cordis contexts.
"""

import asyncio
import inspect
import sys
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

        def _setup():
            async def _tick_loop():
                try:
                    while not self._done:
                        await asyncio.sleep(self.delay_sec)
                        if self._done:
                            break
                        if self._next_future is not None and not self._next_future.done():
                            self._next_future.set_result(None)
                            self._next_future = None
                except asyncio.CancelledError:
                    pass

            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(_tick_loop())
            except RuntimeError:
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

    def __aiter__(self) -> AsyncIterator[None]:
        return self

    @property
    def _disposed(self) -> bool:
        return self._done is not None

    async def __anext__(self) -> None:
        if self._done is not None:
            if self._done["kind"] == "return":
                raise StopAsyncIteration
            raise self._done["reason"]

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._next_future = fut
        try:
            await fut
        finally:
            if self._next_future is fut:
                self._next_future = None

    async def aclose(self) -> None:
        if not self._done:
            self._done = {"kind": "return", "value": None}
            if self._next_future is not None and not self._next_future.done():
                self._next_future.set_exception(StopAsyncIteration())
                self._next_future = None
            if callable(self._dispose):
                self._dispose()

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
        Run a callback once, or return a Future that resolves after delay_ms.
        All timers are automatically cancelled when owning fiber/context is disposed.
        """
        target_ctx = ctx or self.ctx

        if callable(callback_or_delay):
            callback = callback_or_delay
            delay = float(delay_ms if delay_ms is not None else 0)
            delay_sec = max(0.0, delay / 1000.0)

            def _setup():
                timer_handle: Optional[asyncio.TimerHandle] = None
                threading_timer: Optional[threading.Timer] = None
                disposed = False

                def _on_timeout():
                    nonlocal disposed
                    if disposed:
                        return
                    disposed = True
                    if callable(dispose):
                        dispose()
                    try:
                        res = callback()
                        if inspect.isawaitable(res):
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(res)
                            except RuntimeError:
                                pass
                    except Exception as e:
                        if hasattr(target_ctx, "logger"):
                            target_ctx.logger("timer").error("Exception in timeout callback: %s", e)
                        else:
                            sys.stderr.write(f"[Cordis Timer Error] Exception in timeout: {e}\n")

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

            dispose = target_ctx.effect(_setup, "ctx.timeout()")
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
                async def _fallback_sleep():
                    await asyncio.sleep(delay_sec)
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
                task: Optional[asyncio.Task] = None
                threading_timer: Optional[threading.Thread] = None

                async def _async_interval_loop():
                    while not disposed:
                        await asyncio.sleep(delay_sec)
                        if disposed:
                            break
                        try:
                            res = callback()
                            if inspect.isawaitable(res):
                                try:
                                    loop = asyncio.get_running_loop()
                                    loop.create_task(res)
                                except RuntimeError:
                                    pass
                        except Exception as e:
                            if hasattr(target_ctx, "logger"):
                                target_ctx.logger("timer").error("Exception in interval callback: %s", e)

                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(_async_interval_loop())
                except RuntimeError:
                    def _thread_interval():
                        while not disposed:
                            time.sleep(delay_sec)
                            if disposed:
                                break
                            try:
                                callback()
                            except Exception:
                                pass
                    threading_timer = threading.Thread(target=_thread_interval, daemon=True)
                    threading_timer.start()

                def _cleanup():
                    nonlocal disposed
                    disposed = True
                    if task and not task.done():
                        task.cancel()

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
        disposed = False

        def _setup():
            def _cleanup():
                nonlocal disposed, timer_handle
                disposed = True
                if timer_handle is not None:
                    timer_handle.cancel()
                    timer_handle = None
            return _cleanup

        disposer = target_ctx.effect(_setup, "ctx.throttle()")

        def throttled(*args: Any, **kwargs: Any) -> Any:
            nonlocal last_call, timer_handle
            if disposed:
                return None
            now = time.time()
            remaining = delay_sec - (now - last_call)

            def _execute(*a, **kw):
                nonlocal last_call, timer_handle
                last_call = time.time()
                timer_handle = None
                if not disposed:
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
                _execute(*args, **kwargs)
            elif not no_trailing:
                if timer_handle is not None:
                    timer_handle.cancel()
                try:
                    loop = asyncio.get_running_loop()
                    timer_handle = loop.call_later(remaining, lambda a=args, kw=kwargs: _execute(*a, **kw))
                except RuntimeError:
                    pass

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
        disposed = False

        def _setup():
            def _cleanup():
                nonlocal disposed, timer_handle
                disposed = True
                if timer_handle is not None:
                    timer_handle.cancel()
                    timer_handle = None
            return _cleanup

        disposer = target_ctx.effect(_setup, "ctx.debounce()")

        def debounced(*args: Any, **kwargs: Any) -> Any:
            nonlocal timer_handle
            if disposed:
                return None
            if timer_handle is not None:
                timer_handle.cancel()

            def _execute(*a, **kw):
                nonlocal timer_handle
                timer_handle = None
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
                t = threading.Timer(delay_sec, lambda a=args, kw=kwargs: _execute(*a, **kw))
                t.daemon = True
                t.start()

        debounced.dispose = disposer
        return debounced
