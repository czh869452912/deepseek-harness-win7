"""
Cordis Event Bus matching reference/vendor/cordis/src/events.ts
Supports emit, parallel, serial, bail, and waterfall dispatch modes with internal/listener interception.
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


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
    with context filtering, internal/listener interception, and 1:1 bail semantics.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._hooks: Dict[str, List[Hook]] = {}

        # 1:1 Built-in internal/listener handler matching TS EventsService
        def _on_internal_listener(name: str, listener: Any, prepend: bool = False, *args: Any, **kwargs: Any) -> Any:
            target_ctx = kwargs.get("caller_ctx") or (args[0] if args and hasattr(args[0], "fiber") else None) or self.ctx
            if name == "internal/update" and target_ctx and hasattr(target_ctx, "fiber") and target_ctx.fiber:
                fiber = target_ctx.fiber
                if "internal/update" not in fiber._hooks:
                    from dsh.cordis.utils import DisposableList
                    fiber._hooks["internal/update"] = DisposableList()
                hooks = fiber._hooks["internal/update"]
                return hooks.push(listener)
            return None

        self.on("internal/listener", _on_internal_listener, global_listener=True)

        def _on_internal_update(config: Any, no_save: bool = False, *args: Any, **kwargs: Any) -> Any:
            target_ctx = kwargs.get("caller_ctx") or self.ctx
            fiber = getattr(target_ctx, "fiber", None) if target_ctx else None
            cbs = list(fiber._hooks.get("internal/update", [])) if fiber else []

            next_callback = args[-1] if args and callable(args[-1]) else None
            user_next = args[-2] if len(args) >= 2 and callable(args[-2]) else (args[0] if args and callable(args[0]) else None)

            def _next(cfg=config):
                if cbs:
                    cb = cbs.pop(0)
                    return cb(cfg, no_save, _next)
                elif user_next and callable(user_next):
                    return user_next(cfg)
                elif next_callback and callable(next_callback):
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

        # Handle internal/listener interception hook if caller_ctx is present
        if caller_ctx is not None and not event_name.startswith("internal/listener"):
            intercepted = self.bail_sync("internal/listener", event_name, handler, prepend, caller_ctx=caller_ctx)
            if intercepted:
                if callable(intercepted):
                    return intercepted
                return lambda: True

        if event_name not in self._hooks:
            self._hooks[event_name] = []

        hook = Hook(handler, prepend=prepend, global_listener=global_listener, ctx=caller_ctx)
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
        args_or_ctx: Any = None,
        caller_ctx: Any = None,
    ) -> List[Callable[..., Any]]:
        actual_args: List[Any] = []
        actual_ctx = caller_ctx

        if actual_ctx is None:
            if hasattr(args_or_ctx, "filter") or hasattr(args_or_ctx, "registry") or hasattr(args_or_ctx, "reflect"):
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
            if hook.global_listener or actual_ctx is None or hook.ctx is None:
                result_callbacks.append(hook.callback)
            else:
                ctx_filter = getattr(actual_ctx, "filter", None)
                if ctx_filter is None or (callable(ctx_filter) and ctx_filter(hook.ctx)):
                    result_callbacks.append(hook.callback)
        return result_callbacks

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Dispatch an event synchronously, ignoring return values matching TS EventBus.emit.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("emit", event_name, args, caller_ctx)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    pass

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Emit event asynchronously to listeners in sequence.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("emit", event_name, args, caller_ctx)
        for listener in listeners:
            res = listener(*args, **kwargs)
            if inspect.isawaitable(res):
                await res

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Parallel dispatch: run all listeners concurrently.
        Raises AggregateError if any listeners fail.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("parallel", event_name, args, caller_ctx)
        if not listeners:
            return []

        async def _run(cb: Callable[..., Any]) -> Any:
            res = cb(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res

        results = await asyncio.gather(*[_run(cb) for cb in listeners], return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise AggregateError(errors)
        return list(results)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, awaiting listeners in order until one bails.
        """
        caller_ctx = kwargs.pop("caller_ctx", None)
        listeners = self._dispatch_hooks("serial", event_name, args, caller_ctx)
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
        caller_ctx = kwargs.get("caller_ctx")
        listeners = self._dispatch_hooks("bail", event_name, args, caller_ctx)
        for listener in listeners:
            try:
                res = listener(*args, **kwargs)
            except TypeError:
                res = listener(*args)
            if is_bailed(res):
                return res
        return None

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, calling listeners in order until one bails.
        """
        caller_ctx = kwargs.get("caller_ctx")
        listeners = self._dispatch_hooks("bail", event_name, args, caller_ctx)
        for listener in listeners:
            try:
                res = listener(*args, **kwargs)
            except TypeError:
                res = listener(*args)
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def waterfall_sync(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Synchronous waterfall middleware pipeline matching TS waterfall semantics.
        """
        caller_ctx = kwargs.get("caller_ctx")
        listeners = self._dispatch_hooks("waterfall", event_name, [data] + list(args), caller_ctx)

        def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                return current_data
            cb = listeners[index]

            def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return run_pipeline(index + 1, payload)

            sig = inspect.signature(cb)
            params = [
                p.name for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kw = kwargs if has_var_kw else {k: v for k, v in kwargs.items() if k in sig.parameters}

            if len(params) >= 2 or "next" in params or "next_fn" in params:
                return cb(current_data, *args, next_fn, **kw)
            else:
                res = cb(current_data, *args, **kw)
                if res is not None:
                    return next_fn(res)
                return next_fn(current_data)

        return run_pipeline(0, data)

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline matching TS waterfall semantics.
        """
        caller_ctx = kwargs.get("caller_ctx")
        listeners = self._dispatch_hooks("waterfall", event_name, [data] + list(args), caller_ctx)

        async def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                return current_data
            cb = listeners[index]

            async def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return await run_pipeline(index + 1, payload)

            sig = inspect.signature(cb)
            params = [
                p.name for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kw = kwargs if has_var_kw else {k: v for k, v in kwargs.items() if k in sig.parameters}

            if len(params) >= 2 or "next" in params or "next_fn" in params:
                res = cb(current_data, *args, next_fn, **kw)
            else:
                res = cb(current_data, *args, **kw)
                if inspect.isawaitable(res):
                    res = await res
                if res is not None:
                    return await next_fn(res)
                return await next_fn(current_data)

            if inspect.isawaitable(res):
                res = await res
            return res

        return await run_pipeline(0, data)
