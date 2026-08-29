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


def _bind_caller_ctx(cb: Callable[..., Any], caller_ctx: Any) -> Callable[..., Any]:
    if not callable(cb):
        return cb
    try:
        sig = inspect.signature(cb)
        has_caller_ctx = "caller_ctx" in sig.parameters
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_caller_ctx or has_varkw:
            import functools
            @functools.wraps(cb)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                if "caller_ctx" not in kwargs:
                    kwargs["caller_ctx"] = caller_ctx
                return cb(*args, **kwargs)
            return wrapped
    except Exception:
        pass
    return cb


class EventBus:
    """
    Cordis Event Bus supporting emit, waterfall, parallel, serial, and bail dispatch modes
    with context filtering, internal/listener interception, and 1:1 bail semantics.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx
        self._hooks: Dict[str, List[Hook]] = {}

        # 1:1 Built-in internal/listener handler matching TS EventsService
        def _on_internal_listener(name: str, listener: Any, prepend: bool = False, global_listener: bool = False, *args: Any, **kwargs: Any) -> Any:
            if global_listener:
                return None
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
            cbs = list(getattr(fiber, "_hooks", {}).get("internal/update", [])) if fiber else []

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

        # 1:1 Reflect Bind matching TS events.ts:295
        if caller_ctx is not None and hasattr(caller_ctx, "reflect") and hasattr(caller_ctx.reflect, "bind"):
            handler = caller_ctx.reflect.bind(handler)

        # Handle internal/listener interception hook if caller_ctx is present
        if caller_ctx is not None and not event_name.startswith("internal/listener"):
            intercepted = self.bail_sync("internal/listener", event_name, handler, prepend, global_listener, caller_ctx=caller_ctx)
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
            if hook.global_listener or actual_ctx is None or hook.ctx is None:
                if actual_ctx is not None:
                    cb = _bind_caller_ctx(cb, actual_ctx)
                result_callbacks.append(cb)
            else:
                ctx_filter = getattr(actual_ctx, "filter", None)
                if ctx_filter is None:
                    if actual_ctx is not None:
                        cb = _bind_caller_ctx(cb, actual_ctx)
                    result_callbacks.append(cb)
                elif callable(ctx_filter):
                    try:
                        if ctx_filter(hook.ctx):
                            if actual_ctx is not None:
                                cb = _bind_caller_ctx(cb, actual_ctx)
                            result_callbacks.append(cb)
                    except Exception:
                        pass
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
                try:
                    res = listener(*args)
                except TypeError:
                    if len(args) > 1:
                        try:
                            res = listener(*args[:-1])
                        except TypeError:
                            res = None
                    else:
                        res = None
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
                try:
                    res = listener(*args)
                except TypeError:
                    if len(args) > 1:
                        try:
                            res = listener(*args[:-1])
                        except TypeError:
                            res = None
                    else:
                        res = None
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def waterfall_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Synchronous waterfall middleware pipeline matching TS waterfall semantics.
        Supports both Koa-style (cb(*args, next)) and reducer style (cb(current_data, *args)).
        """
        caller_ctx = kwargs.get("caller_ctx") or self.ctx
        kwargs["caller_ctx"] = caller_ctx
        args_list = list(args)
        inner = args_list.pop() if args_list and callable(args_list[-1]) else None
        data = args_list.pop(0) if args_list else None

        listeners = self._dispatch_hooks("waterfall", event_name, [data] + args_list, caller_ctx)

        def _call_inner(fn: Any, val: Any) -> Any:
            if not callable(fn):
                return fn
            try:
                sig = inspect.signature(fn)
                if len(sig.parameters) == 0:
                    return fn()
                return fn(val)
            except (ValueError, TypeError):
                try:
                    return fn(val)
                except TypeError:
                    return fn()

        def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                if inner is not None:
                    return _call_inner(inner, current_data)
                return current_data

            cb = listeners[index]

            def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return run_pipeline(index + 1, payload)

            sig = inspect.signature(cb)
            params = list(sig.parameters.keys())
            has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kw = kwargs if has_var_kw else {k: v for k, v in kwargs.items() if k in sig.parameters}

            if "next" in params or "next_fn" in params or len(params) == len(args_list) + 2 or has_var_pos:
                try:
                    return cb(current_data, *args_list, next_fn, **kw)
                except TypeError:
                    pass

            res = cb(current_data, *args_list, **kw)
            if res is not None:
                return next_fn(res)
            return next_fn(current_data)

        return run_pipeline(0, data)

    async def waterfall(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Waterfall middleware pipeline matching TS waterfall semantics.
        Supports both Koa-style (cb(*args, next)) and reducer style (cb(current_data, *args)).
        """
        caller_ctx = kwargs.get("caller_ctx") or self.ctx
        kwargs["caller_ctx"] = caller_ctx
        args_list = list(args)
        inner = args_list.pop() if args_list and callable(args_list[-1]) else None
        data = args_list.pop(0) if args_list else None

        listeners = self._dispatch_hooks("waterfall", event_name, [data] + args_list, caller_ctx)

        async def _call_inner_async(fn: Any, val: Any) -> Any:
            if not callable(fn):
                return fn
            try:
                sig = inspect.signature(fn)
                res = fn() if len(sig.parameters) == 0 else fn(val)
            except (ValueError, TypeError):
                try:
                    res = fn(val)
                except TypeError:
                    res = fn()
            if inspect.isawaitable(res):
                return await res
            return res

        async def run_pipeline(index: int, current_data: Any) -> Any:
            if index >= len(listeners):
                if inner is not None:
                    return await _call_inner_async(inner, current_data)
                return current_data

            cb = listeners[index]

            async def next_fn(next_data: Any = None) -> Any:
                payload = current_data if next_data is None else next_data
                return await run_pipeline(index + 1, payload)

            sig = inspect.signature(cb)
            params = list(sig.parameters.keys())
            has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kw = kwargs if has_var_kw else {k: v for k, v in kwargs.items() if k in sig.parameters}

            if "next" in params or "next_fn" in params or len(params) == len(args_list) + 2 or has_var_pos:
                try:
                    res = cb(current_data, *args_list, next_fn, **kw)
                except TypeError:
                    res = cb(current_data, *args_list, **kw)
            else:
                res = cb(current_data, *args_list, **kw)

            if inspect.isawaitable(res):
                res = await res

            if "next" in params or "next_fn" in params:
                return res

            if res is not None:
                return await next_fn(res)
            return await next_fn(current_data)

        return await run_pipeline(0, data)
