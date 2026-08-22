import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple


def is_bailed(value: Any) -> bool:
    """
    Return whether an event result should stop a bail-style dispatch.
    Returns True unless value is None or False.
    """
    return value is not None and value is not False


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
        self._hooks: Dict[str, List[Hook]] = {}

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
        if event_name not in self._hooks:
            self._hooks[event_name] = []

        hook = Hook(handler, prepend=prepend, global_listener=global_listener, ctx=ctx)
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

    def _dispatch_hooks(self, dispatch_type: str, event_name: str, caller_ctx: Any = None) -> List[Callable[..., Any]]:
        if not event_name.startswith("internal/"):
            # Fired for non-internal events to diagnose dispatches
            self.emit("internal/dispatch", dispatch_type, event_name, caller_ctx)

        hooks = list(self._hooks.get(event_name, []))
        result_callbacks = []
        for hook in hooks:
            if hook.global_listener or caller_ctx is None or hook.ctx is None:
                result_callbacks.append(hook.callback)
            else:
                # Check context scope filtering if defined
                ctx_filter = getattr(caller_ctx, "filter", None)
                if ctx_filter is None or ctx_filter(hook.ctx):
                    result_callbacks.append(hook.callback)
        return result_callbacks

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Dispatch an event synchronously, ignoring return values.
        """
        listeners = self._dispatch_hooks("emit", event_name, kwargs.pop("caller_ctx", None))
        for listener in listeners:
            try:
                res = listener(*args, **kwargs)
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                print(f"[Cordis Event Error] Exception in emit '{event_name}': {e}", file=sys.stderr)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event asynchronously to listeners in sequence.
        """
        listeners = self._dispatch_hooks("emit", event_name, kwargs.pop("caller_ctx", None))
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                await res

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Parallel dispatch: run all listeners concurrently using asyncio.gather.
        """
        listeners = self._dispatch_hooks("parallel", event_name, kwargs.pop("caller_ctx", None))
        tasks = []
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                tasks.append(res)
            else:
                async def _wrap(val=res):
                    return val
                tasks.append(_wrap())

        if not tasks:
            return []
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, awaiting listeners in order until one bails.
        """
        listeners = self._dispatch_hooks("serial", event_name, kwargs.pop("caller_ctx", None))
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
        listeners = self._dispatch_hooks("bail", event_name, kwargs.pop("caller_ctx", None))
        for listener in listeners:
            res = listener(*args, **kwargs)
            if is_bailed(res):
                return res
        return None

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, calling listeners in order until one bails.
        """
        listeners = self._dispatch_hooks("bail", event_name, kwargs.pop("caller_ctx", None))
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def waterfall_sync(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Synchronous waterfall middleware pipeline for non-async event chains.
        """
        listeners = self._dispatch_hooks("waterfall", event_name, kwargs.pop("caller_ctx", None))

        def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                return current_data
            listener = listeners[index]

            def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return run_pipeline(index + 1, payload)

            sig = inspect.signature(listener)
            param_names = [
                p.name for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_next = "next_fn" in param_names or "next" in param_names

            if has_next:
                return listener(current_data, *args, next_fn, **kwargs)
            else:
                res = listener(current_data, *args, **kwargs)
                if res is not None:
                    return next_fn(res)
                return next_fn(current_data)

        return run_pipeline(0, data)

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline.
        Listeners are called with (data, *args, next_fn).
        Calling next_fn(modified_data) invokes downstream listeners.
        Short-circuiting occurs if next_fn is not called.
        """
        listeners = self._dispatch_hooks("waterfall", event_name, kwargs.pop("caller_ctx", None))

        async def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                return current_data

            listener = listeners[index]

            async def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return await run_pipeline(index + 1, payload)

            sig = inspect.signature(listener)
            param_names = [
                p.name for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_next = "next_fn" in param_names or "next" in param_names

            if has_next:
                res = listener(current_data, *args, next_fn, **kwargs)
            else:
                res = listener(current_data, *args, **kwargs)
                if inspect.isawaitable(res):
                    res = await res
                if res is not None:
                    return await next_fn(res)
                return await next_fn(current_data)

            if inspect.isawaitable(res):
                res = await res
            return res

        return await run_pipeline(0, data)
