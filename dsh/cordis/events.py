"""
Cordis Event Bus matching reference/vendor/cordis/src/events.ts
Supports emit, parallel, serial, bail, and waterfall dispatch modes.
"""

import asyncio
import inspect
from typing import Any, Callable, Dict, List


def is_bailed(value: Any) -> bool:
    """
    Return whether an event result should stop a bail-style dispatch.
    Returns True unless value is None or False.
    """
    return value is not None and value is not False


class AggregateError(Exception):
    """Aggregated exception raised by parallel dispatch when listeners fail."""
    def __init__(self, errors: List[Exception]):
        self.errors = errors
        msg = f"AggregateError ({len(errors)} errors):\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


class Hook:
    """Registered listener record stored by the event service."""
    def __init__(self, callback: Callable[..., Any], prepend: bool = False, global_listener: bool = False, ctx: Any = None):
        self.callback = callback
        self.prepend = prepend
        self.global_listener = global_listener
        self.ctx = ctx


class EventBus:
    """
    Cordis Event Bus supporting emit, waterfall, parallel, serial, and bail dispatch modes
    with context filtering and 1:1 bail semantics.
    """

    def __init__(self):
        local_events = (
            "internal/config",
            "internal/get",
            "internal/set",
            "internal/update",
        )
        self._fiber_bridges = {
            event_name: Hook(lambda: None, global_listener=True)
            for event_name in local_events
        }
        self._hooks: Dict[str, List[Hook]] = {
            event_name: [bridge]
            for event_name, bridge in self._fiber_bridges.items()
        }

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
        hook = Hook(handler, prepend=prepend, global_listener=global_listener, ctx=ctx)
        if event_name in self._fiber_bridges and not global_listener and ctx is not None:
            fiber = getattr(ctx, "fiber", None)
            if fiber is not None:
                fiber_hooks = getattr(fiber, "_hooks", None)
                if fiber_hooks is None:
                    fiber_hooks = {}
                    setattr(fiber, "_hooks", fiber_hooks)
                hooks = fiber_hooks.setdefault(event_name, [])
                if prepend:
                    hooks.insert(0, hook)
                else:
                    hooks.append(hook)

                def dispose_fiber_hook() -> bool:
                    if hook not in hooks:
                        return False
                    hooks.remove(hook)
                    return True

                return dispose_fiber_hook

        if event_name not in self._hooks:
            self._hooks[event_name] = []

        if prepend:
            self._hooks[event_name].insert(0, hook)
        else:
            self._hooks[event_name].append(hook)

        def disposer() -> bool:
            if event_name in self._hooks and hook in self._hooks[event_name]:
                self._hooks[event_name].remove(hook)
                return True
            return False

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
            return handler(*args, **kwargs)

        disposer = self.on(event_name, wrapper, prepend=prepend, global_listener=global_listener, ctx=ctx)
        return disposer

    def _dispatch_hooks(
        self,
        dispatch_type: str,
        event_name: str,
        caller_ctx: Any = None,
        event_args: Any = None,
    ) -> List[Callable[..., Any]]:
        if not event_name.startswith("internal/"):
            # Fired for non-internal events to diagnose dispatches
            self.emit(
                "internal/dispatch",
                dispatch_type,
                event_name,
                list(event_args or []),
                caller_ctx,
            )

        result_callbacks = []
        for hook in self._hooks.get(event_name, []):
            if hook is self._fiber_bridges.get(event_name):
                if caller_ctx is not None:
                    fiber = getattr(caller_ctx, "fiber", None)
                    fiber_hooks = (
                        getattr(fiber, "_hooks", {})
                        if fiber is not None
                        else {}
                    )
                    result_callbacks.extend(
                        item.callback
                        for item in fiber_hooks.get(event_name, [])
                    )
                continue
            if hook.global_listener or caller_ctx is None or hook.ctx is None:
                result_callbacks.append(hook.callback)
            else:
                namespace = getattr(caller_ctx, "__dict__", {})
                ctx_filter = namespace.get("_event_filter", namespace.get("filter"))
                if ctx_filter is None or ctx_filter(hook.ctx):
                    result_callbacks.append(hook.callback)
        return result_callbacks

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Dispatch an event synchronously, ignoring return values.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("emit", event_name, caller_ctx, args)
        for listener in listeners:
            result = listener(*args, **kwargs)
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    result.close()
                else:
                    loop.create_task(result)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event asynchronously to listeners in sequence.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("emit", event_name, caller_ctx, args)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                await res

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Parallel dispatch: run all listeners concurrently.
        Raises AggregateError if any listeners fail.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("emit", event_name, caller_ctx, args)
        if not listeners:
            return None

        async def _run(cb: Callable[..., Any]) -> Any:
            res = cb(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res

        results = await asyncio.gather(*[_run(cb) for cb in listeners], return_exceptions=True)
        cancellations = [
            result
            for result in results
            if isinstance(result, asyncio.CancelledError)
        ]
        if cancellations:
            raise cancellations[0]
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise AggregateError(errors)
        return None

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, awaiting listeners in order until one bails.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("serial", event_name, caller_ctx, args)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def bail_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event synchronously, stopping on the first bail value.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("bail", event_name, caller_ctx, args)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if is_bailed(res):
                return res
        return None

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, calling listeners in order until one bails.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("bail", event_name, caller_ctx, args)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def waterfall_sync(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Synchronous waterfall middleware pipeline matching TS waterfall semantics.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        raw_args = [data] + list(args)
        listeners = self._dispatch_hooks(
            "waterfall", event_name, caller_ctx, raw_args
        )
        inner = raw_args.pop() if raw_args and callable(raw_args[-1]) else (lambda *values, **_kw: values[0] if values else None)
        callbacks = list(listeners)

        def next_fn() -> Any:
            if not callbacks:
                return inner(*raw_args, **kwargs)
            callback = callbacks.pop(0)
            return callback(*raw_args, next_fn, **kwargs)

        return next_fn()

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline matching TS waterfall semantics.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        raw_args = [data] + list(args)
        listeners = self._dispatch_hooks(
            "waterfall", event_name, caller_ctx, raw_args
        )
        inner = raw_args.pop() if raw_args and callable(raw_args[-1]) else (lambda *values, **_kw: values[0] if values else None)
        callbacks = list(listeners)

        async def next_fn(*next_args: Any) -> Any:
            call_args = list(next_args) if next_args else list(raw_args)
            if callbacks:
                callback = callbacks.pop(0)
                result = callback(*call_args, next_fn, **kwargs)
            else:
                result = inner(*call_args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        return await next_fn()
