"""
Cordis Event Bus matching reference/vendor/cordis/src/events.ts
Supports emit, parallel, serial, bail, and waterfall dispatch modes with internal/listener interception.
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


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
        intercepted = self.bail_sync("internal/listener", event_name, handler, options, caller_ctx=caller_ctx or self.ctx)
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
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
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
                    loop.create_task(res)
                except RuntimeError:
                    pass

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

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Parallel dispatch: run all listeners concurrently matching TS EventBus.parallel.
        Raises AggregateError if any listeners fail.
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
        if not listeners:
            return []

        async def _run(cb: Callable[..., Any]) -> Any:
            res = cb(*actual_args, **kwargs)
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
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("serial", event_name, actual_args, caller_ctx)
        for listener in listeners:
            res = listener(*actual_args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

    def bail_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
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

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatch an event, calling listeners in order until one bails matching TS EventBus.bail.
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
            if inspect.isawaitable(res):
                res = await res
            if is_bailed(res):
                return res
        return None

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
