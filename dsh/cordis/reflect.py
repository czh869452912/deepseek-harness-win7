"""
Reflection and service-resolution layer matching reference/vendor/cordis/src/reflect.ts
"""

import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


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


RESERVED_PROPERTIES = {"prototype", "then", "_services", "_parent", "_event_bus", "registry", "reflect", "fiber", "root"}


class ReflectService:
    """
    Reflection layer backing Context service resolution, proxy lookups, accessors, and mixins.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.store: Dict[Any, Impl] = {}
        self.props: Dict[str, Any] = {}

    def setup_mixins(self) -> None:
        """Mixin core service APIs onto context."""
        self.mixin("reflect", ["get", "set", "provide", "accessor", "mixin"])
        self.mixin("fiber", ["runtime", "effect"])
        self.mixin("registry", ["inject", "plugin"])
        self.mixin("events", ["on", "once", "parallel", "emit", "serial", "bail", "waterfall"])

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

        # 2. Direct service dictionary check on Context
        if hasattr(ctx, "_services") and name in ctx._services:
            val = ctx._services[name]
            return self._fire_get_waterfall(ctx, name, val)

        # 3. Store implementation check
        impl = self._get_impl(ctx, name, strict=strict)
        if impl is not None:
            return self._fire_get_waterfall(ctx, name, impl.value)

        # Fallback parent hierarchy check
        if hasattr(ctx, "get_service"):
            val = ctx.get_service(name, default)
            if val is not default:
                return self._fire_get_waterfall(ctx, name, val)

        return default

    def _fire_get_waterfall(self, ctx: Any, name: str, value: Any) -> Any:
        if hasattr(ctx, "waterfall_sync"):
            err = RuntimeError(f"get {name}")
            return ctx.waterfall_sync("internal/get", value, ctx, name, err)
        return value

    def _get_impl(self, ctx: Any, name: str, strict: bool = True) -> Optional[Impl]:
        isolated_map = getattr(ctx, "_isolated_keys", {})
        if name in isolated_map:
            key = isolated_map[name]
            impl = self.store.get(key)
        else:
            impl = self.store.get(name)
        if not impl:
            return None
        if strict and hasattr(impl.fiber, "state"):
            from dsh.cordis.fiber import FiberState
            if impl.fiber.state != FiberState.ACTIVE:
                return None
        return impl

    def set(self, ctx: Any, name: str, value: Any) -> bool:
        """
        Overwrite a provided service's value.
        """
        def_prop = self.props.get(name)
        if def_prop and getattr(def_prop, "type", None) == PropertyType.ACCESSOR:
            if not def_prop.set:
                return False
            err = KeyError(f"cannot set property '{name}'")
            return def_prop.set(ctx, value, err)

        isolated_map = getattr(ctx, "_isolated_keys", {})
        key = isolated_map.get(name, name)
        impl = self.store.get(key) or self.store.get(name)
        if impl:
            if hasattr(ctx, "fiber") and impl.fiber and impl.fiber != ctx.fiber:
                pass
            impl.value = value

        if hasattr(ctx, "_services"):
            ctx._services[name] = value
            setattr(ctx, name, value)
        return True

    def provide(self, ctx: Any, name: str, value: Any = None, check: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
        """
        Register a service implementation owned by the current fiber.
        """
        target_ctx = ctx or self.ctx

        def setup() -> Callable[[], Any]:
            if name not in self.props:
                self.props[name] = PropertyService()
            elif getattr(self.props[name], "type", None) != PropertyType.SERVICE:
                raise RuntimeError(f"property '{name}' is already declared as {self.props[name].type}")

            isolated_map = getattr(target_ctx, "_isolated_keys", {})
            key = isolated_map.get(name, name)

            fiber = getattr(target_ctx, "fiber", None)
            impl = Impl(name=name, fiber=fiber, value=value, check=check)

            self.store[key] = impl
            if hasattr(target_ctx, "_services"):
                target_ctx._services[name] = value
                setattr(target_ctx, name, value)

            if fiber and hasattr(fiber, "store") and fiber.store is not None:
                fiber.store[name] = impl

            from dsh.cordis.fiber import FiberState
            if fiber and fiber.state == FiberState.ACTIVE:
                self.notify([name])

            def teardown() -> None:
                if key in self.store:
                    del self.store[key]
                if hasattr(target_ctx, "_services") and name in target_ctx._services:
                    del target_ctx._services[name]
                    if hasattr(target_ctx, name):
                        try:
                            delattr(target_ctx, name)
                        except AttributeError:
                            pass
                self.notify([name])

            return teardown

        if hasattr(target_ctx, "effect"):
            return target_ctx.effect(setup, label=f"ctx.provide('{name}')")
        else:
            teardown_fn = setup()
            return teardown_fn

    def notify(self, names: List[str]) -> List[Any]:
        """
        Re-evaluate every fiber that requires one of the given services.
        """
        affected_fibers: List[Any] = []
        if hasattr(self.ctx, "registry") and hasattr(self.ctx.registry, "update_dependencies"):
            self.ctx.registry.update_dependencies()

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
