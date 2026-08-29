"""
Reflection and service-resolution layer matching reference/vendor/cordis/src/reflect.ts
"""

import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dsh.cordis.utils import symbols


class PropertyType:
    SERVICE = "service"
    ACCESSOR = "accessor"


class PropertyAccessor:
    def __init__(
        self,
        get_fn: Callable[[Any, Exception], Any],
        set_fn: Optional[Callable[[Any, Any, Exception], bool]] = None,
    ):
        self.type = PropertyType.ACCESSOR
        self.get = get_fn
        self.set = set_fn


class PropertyService:
    def __init__(self):
        self.type = PropertyType.SERVICE


class Impl:
    """Concrete service implementation record."""
    def __init__(self, name: str, fiber: Any, value: Any = None, check: Optional[Callable[[], bool]] = None):
        self.name = name
        self.fiber = fiber
        self.value = value
        self.check = check

    def __repr__(self) -> str:
        return f"<Impl {self.name} fiber={getattr(self.fiber, 'name', 'root')}>"


RESERVED_PROPERTIES = {
    "prototype", "then", "_services", "_parent", "_event_bus", "registry",
    "reflect", "fiber", "root", "_isolated_keys", "_intercept_map", "_effects", "logger", "timer"
}


class ReflectService:
    """
    Reflection layer backing Context service resolution, proxy lookups, accessors, and mixins.
    Matching reference/vendor/cordis/src/reflect.ts.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.store: Dict[Any, Impl] = {}
        self.props: Dict[str, Any] = {}

    def setup_mixins(self) -> None:
        """Mixin core service APIs onto context."""
        self.mixin("reflect", ["get", "set", "provide", "accessor", "mixin", "trace", "bind"])
        self.mixin("fiber", ["runtime", "effect"])
        self.mixin("registry", ["inject", "plugin"])
        self.mixin("events", ["on", "once", "parallel", "emit", "serial", "bail", "waterfall"])
        self.mixin("logger", ["error", "info", "warn", "debug"])
        self.mixin("timer", ["timeout", "interval", "throttle", "debounce", "setTimeout", "setInterval"])

    def get(self, ctx: Any, name: str, default: Any = None, strict: bool = True) -> Any:
        """
        Read a service or accessor property from context.
        """
        if name in RESERVED_PROPERTIES or name.startswith("_"):
            return getattr(ctx, name, default)

        # 1. Accessor check
        def_prop = self.props.get(name)
        if def_prop and getattr(def_prop, "type", None) == PropertyType.ACCESSOR:
            err = KeyError(f"cannot get property '{name}'")
            return def_prop.get(ctx, err)

        def _resolve_default():
            # 2. Store implementation check
            impl = self._get_impl(ctx, name, strict=strict)
            if impl is not None:
                val = impl.value
                if getattr(val, "ctx", None) is ctx:
                    return val
                from dsh.cordis.utils import get_traceable
                return get_traceable(ctx, val)

            # 3. Direct service dictionary check on Context
            if hasattr(ctx, "_services") and name in ctx._services:
                val = ctx._services[name]
                if getattr(val, "ctx", None) is ctx:
                    return val
                from dsh.cordis.utils import get_traceable
                return get_traceable(ctx, val)

            # 4. Fallback parent hierarchy check
            if hasattr(ctx, "get_service"):
                val = ctx.get_service(name, default)
                if val is not default:
                    if getattr(val, "ctx", None) is ctx:
                        return val
                    from dsh.cordis.utils import get_traceable
                    return get_traceable(ctx, val)

            return default

        err = RuntimeError(f"cannot get property '{name}'")
        if hasattr(ctx, "waterfall_sync"):
            return ctx.waterfall_sync("internal/get", ctx, name, err, _resolve_default)
        return _resolve_default()

    def _get_impl(self, ctx: Any, name: str, strict: bool = True) -> Optional[Impl]:
        isolated_map = getattr(ctx, "_isolated_keys", {})
        if name in isolated_map:
            key = isolated_map[name]
            impl = self.store.get(key)
        else:
            impl = self.store.get(name)
        if not impl:
            return None
        if strict and impl.fiber is not None and getattr(impl.fiber, "plugin", None) is not None:
            from dsh.cordis.fiber import FiberState
            if impl.fiber.state != FiberState.ACTIVE:
                return None
        return impl

    def set(self, ctx: Any, name: str, value: Any) -> bool:
        """
        Overwrite a provided service's value matching TS ReflectService.set.
        """
        def_prop = self.props.get(name)
        if def_prop and getattr(def_prop, "type", None) == PropertyType.ACCESSOR:
            if not def_prop.set:
                return False
            err = RuntimeError(f"cannot set property '{name}'")
            return def_prop.set(ctx, value, err)

        def _do_set():
            isolated_map = getattr(ctx, "_isolated_keys", {})
            key = isolated_map.get(name, name)
            impl = self.store.get(key) or self.store.get(name)
            if not impl:
                raise RuntimeError(f"cannot set property '{name}' without provide")

            fiber = getattr(ctx, "fiber", None)
            if fiber is not None and impl.fiber is not None and impl.fiber is not fiber and getattr(fiber, "uid", None) not in (0, None):
                raise RuntimeError(f"cannot set property '{name}' in multiple fibers")

            impl.value = value

            target = ctx.root if hasattr(ctx, "root") else ctx
            if hasattr(target, "_services"):
                target._services[name] = value
                setattr(target, name, value)
            return True

        err = RuntimeError(f"cannot set property '{name}' without provide")
        if hasattr(ctx, "waterfall_sync"):
            return ctx.waterfall_sync("internal/set", ctx, name, value, err, _do_set)
        return _do_set()

    def provide(
        self,
        ctx_or_name: Any,
        name_or_value: Any = None,
        value: Any = None,
        check: Optional[Callable[[], bool]] = None,
        allow_replace: bool = False,
    ) -> Callable[[], None]:
        """
        Register a service implementation owned by the current fiber.
        Supports both (ctx, name, value, check) and (name, value, check) signatures.
        """
        if isinstance(ctx_or_name, str):
            target_ctx = self.ctx
            name = ctx_or_name
            val = name_or_value
            chk = value if callable(value) else check
        else:
            target_ctx = ctx_or_name or self.ctx
            name = name_or_value
            val = value
            chk = check

        def setup() -> Callable[[], Any]:
            if name not in self.props:
                self.props[name] = PropertyService()
            elif getattr(self.props[name], "type", None) != PropertyType.SERVICE:
                raise RuntimeError(f"property '{name}' is already declared as {self.props[name].type}")

            isolated_map = getattr(target_ctx, "_isolated_keys", {})
            key = isolated_map.get(name, name)

            fiber = getattr(target_ctx, "fiber", None)
            if not allow_replace and key in self.store and self.store[key].fiber is not None and self.store[key].fiber is not fiber:
                prev_fiber = self.store[key].fiber
                from dsh.cordis.fiber import FiberState
                if (
                    getattr(prev_fiber, "state", None) not in (FiberState.DISPOSED, FiberState.FAILED)
                    and getattr(fiber, "runtime", None) is not None
                    and getattr(prev_fiber, "runtime", None) is not None
                ):
                    prev_name = getattr(prev_fiber, "name", "unknown")
                    raise RuntimeError(f"service '{name}' has been registered at <{prev_name}>")

            impl = Impl(name=name, fiber=fiber, value=val, check=chk)

            self.store[key] = impl
            target_store = target_ctx if name in isolated_map else (target_ctx.root if hasattr(target_ctx, "root") else target_ctx)
            if hasattr(target_store, "_services"):
                target_store._services[name] = val
                setattr(target_store, name, val)

            if fiber and hasattr(fiber, "store") and fiber.store is not None:
                fiber.store[name] = impl

            from dsh.cordis.fiber import FiberState
            if fiber is None or fiber.state in (FiberState.ACTIVE, FiberState.LOADING):
                self.notify([name])

            def teardown() -> None:
                if key in self.store and self.store[key] == impl:
                    del self.store[key]
                if hasattr(target_store, "_services") and name in target_store._services:
                    del target_store._services[name]
                    if hasattr(target_store, name):
                        try:
                            delattr(target_store, name)
                        except AttributeError:
                            pass
                self.notify([name])

            return teardown

        if hasattr(target_ctx, "effect"):
            return target_ctx.effect(setup, label=f"ctx.provide('{name}')")
        else:
            teardown_fn = setup()
            return teardown_fn

    def notify(self, names: List[str], filter_fn: Optional[Callable[[Any, str], bool]] = None) -> List[Any]:
        """
        1:1 Dependency notification matching TS Cordis ReflectService.notify.
        Re-evaluates every registered fiber that requires one of the changed services.
        """
        affected_fibers: List[Any] = []
        if hasattr(self.ctx, "registry"):
            for fiber in self.ctx.registry.list_fibers():
                has_update = False
                fiber_ctx = getattr(fiber, "ctx", None)
                for name in names:
                    if name in getattr(fiber, "inject", {}):
                        if filter_fn is not None:
                            if fiber_ctx is not None and not filter_fn(fiber_ctx, name):
                                continue
                        else:
                            if fiber_ctx is not None:
                                target_iso = getattr(fiber_ctx, "_isolated_keys", {}).get(name)
                                self_iso = getattr(self.ctx, "_isolated_keys", {}).get(name)
                                if target_iso != self_iso:
                                    continue
                        has_update = True
                        if hasattr(fiber, "_checkImpl"):
                            fiber._checkImpl(name)
                if has_update:
                    if hasattr(fiber, "_refresh"):
                        fiber._refresh()
                    affected_fibers.append(fiber)

        if hasattr(self.ctx, "emit"):
            for name in names:
                impl = self.store.get(name)
                val = impl.value if impl else getattr(self.ctx, name, None)
                self.ctx.emit("internal/service", self.ctx, name, val)
        return affected_fibers

    def accessor(self, name: str, options: Dict[str, Any]) -> Callable[[], None]:
        """
        Define a computed context property backed by get/set hooks.
        """
        def setup() -> Callable[[], None]:
            if name in self.props:
                raise RuntimeError(f"property '{name}' is already declared as {self.props[name].type}")
            get_fn = options.get("get")
            set_fn = options.get("set")
            self.props[name] = PropertyAccessor(get_fn, set_fn)

            def teardown() -> None:
                if name in self.props:
                    del self.props[name]

            return teardown

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(setup, label=f"ctx.accessor('{name}')")
        else:
            return setup()

    def mixin(self, source: Any, mixins: Union[List[str], Dict[str, str]]) -> Callable[[], None]:
        """
        Expose selected members of a service or property directly on `ctx`.
        """
        entries = mixins.items() if isinstance(mixins, dict) else [(k, k) for k in mixins]
        disposers: List[Callable[[], None]] = []

        for src_key, target_key in entries:
            def make_get(s_key: str):
                def get_fn(ctx_self: Any, err: Exception) -> Any:
                    target_obj = getattr(ctx_self, source) if isinstance(source, str) and hasattr(ctx_self, source) else source
                    if target_obj is None:
                        return None
                    attr_val = getattr(target_obj, s_key, None)
                    if callable(attr_val):
                        return attr_val
                    return attr_val
                return get_fn

            def make_set(s_key: str):
                def set_fn(ctx_self: Any, val: Any, err: Exception) -> bool:
                    target_obj = getattr(ctx_self, source) if isinstance(source, str) and hasattr(ctx_self, source) else source
                    if target_obj is None:
                        return False
                    setattr(target_obj, s_key, val)
                    return True
                return set_fn

            disp = self.accessor(target_key, {"get": make_get(src_key), "set": make_set(src_key)})
            disposers.append(disp)

        def cleanup_all() -> None:
            for d in disposers:
                try:
                    d()
                except Exception:
                    pass

        return cleanup_all

    def trace(self, value: Any) -> Any:
        """
        Attach this context's tracing wrapper to a value matching TS reflect.trace().
        """
        from dsh.cordis.utils import get_traceable
        return get_traceable(self.ctx, value)

    def bind(self, callback: Callable[..., Any]) -> Callable[..., Any]:
        """
        Wrap a callback so calls trace receiver and arguments to this context
        matching TS reflect.bind().
        """
        if not callable(callback):
            return callback
        ctx = self.ctx
        from dsh.cordis.utils import get_traceable
        import functools

        @functools.wraps(callback)
        def traced_wrapper(*args: Any, **kwargs: Any) -> Any:
            traced_args = [get_traceable(ctx, arg) for arg in args]
            traced_kwargs = {k: get_traceable(ctx, v) for k, v in kwargs.items()}
            return callback(*traced_args, **traced_kwargs)

        return traced_wrapper
