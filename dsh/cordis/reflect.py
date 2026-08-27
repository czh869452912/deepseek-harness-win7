"""
Reflection and service-resolution layer matching reference/vendor/cordis/src/reflect.ts
"""

import sys
from typing import Any, Callable, Dict, List, Optional, Union

from dsh.cordis.utils import get_traceable


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
        ctx._event_bus.on(
            "internal/status",
            self._on_fiber_status,
            global_listener=True,
            ctx=ctx,
        )

    def _on_fiber_status(self, fiber: Any = None, old_state: int = -1) -> None:
        from dsh.cordis.fiber import FiberState

        # Agent status notifications use the canonical payload envelope while
        # Fiber lifecycle notifications retain the historical positional
        # `(fiber, old_state)` form.  Reflection only reacts to Fiber objects;
        # ignore unrelated internal/status payloads without raising.
        if isinstance(fiber, dict):
            fiber = fiber.get("fiber")
            if fiber is None:
                return

        if fiber.state != FiberState.ACTIVE or old_state == FiberState.ACTIVE:
            return
        names = [impl.name for impl in (fiber.store or {}).values()
                 if getattr(impl, "fiber", None) is fiber]
        if names:
            self.notify(names, fiber.ctx)

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

        error = RuntimeError(f"cannot get property '{name}' without inject")
        if hasattr(ctx, "waterfall_sync"):
            return ctx.waterfall_sync(
                "internal/get",
                ctx,
                name,
                error,
                lambda *_args: self._get_value(
                    ctx,
                    name,
                    default,
                    strict,
                ),
            )
        return self._get_value(ctx, name, default, strict)

    def _get_value(self, ctx: Any, name: str, default: Any, strict: bool) -> Any:
        """Resolve the built-in value after read middleware delegates."""

        if not strict and hasattr(ctx, "get_service"):
            marker = object()
            cached = ctx.get_service(name, marker)
            if cached is not marker:
                return cached
        impl = self._get_impl(ctx, name, strict=strict)
        if impl is not None:
            return impl.value
        return default

    def get_property(self, ctx: Any, name: str) -> Any:
        """Resolve a normal context attribute with upstream inject checks."""
        def_prop = self.props.get(name)
        if def_prop and getattr(def_prop, "type", None) == PropertyType.ACCESSOR:
            return def_prop.get(ctx, RuntimeError(
                'cannot get property "%s" without inject' % name
            ))

        fiber = getattr(ctx, "fiber", None)
        if fiber is None or fiber.runtime is None:
            value = self.get(ctx, name, default=None, strict=False)
            if value is not None:
                return get_traceable(ctx, value)
            raise AttributeError(name)

        key = getattr(ctx, "_isolated_keys", {}).get(name, name)
        current = fiber
        while current is not None:
            store = getattr(current, "store", None)
            impl = store.get(name) if store else None
            if impl is not None:
                return get_traceable(ctx, impl.value)
            if name in getattr(current, "inject", {}):
                raise RuntimeError(
                    'cannot get required service "%s" in inactive context' % name
                )
            if current.runtime is None:
                break
            parent = current.parent
            parent_key = getattr(parent, "_isolated_keys", {}).get(name, name)
            if parent_key != key:
                break
            current = getattr(parent, "fiber", None)
        raise RuntimeError('cannot get property "%s" without inject' % name)

    def _get_impl(self, ctx: Any, name: str, strict: bool = True) -> Optional[Impl]:
        isolated_map = getattr(ctx, "_isolated_keys", {})
        key = isolated_map.get(name, name)
        impl = self.store.get(key)
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

        if hasattr(ctx, "waterfall_sync"):
            err = RuntimeError(f"set {name}")
            return ctx.waterfall_sync(
                "internal/set",
                ctx,
                name,
                value,
                err,
                lambda *_args: self._set_value(ctx, name, value),
            )
        return self._set_value(ctx, name, value)

    def _set_value(self, ctx: Any, name: str, value: Any) -> bool:
        """Apply the built-in service assignment after update middleware."""

        isolated_map = getattr(ctx, "_isolated_keys", {})
        key = isolated_map.get(name, name)
        impl = self.store.get(key)
        if impl is None:
            raise RuntimeError(f'cannot set property "{name}" without provide')
        if impl.fiber is not getattr(ctx, "fiber", None):
            raise RuntimeError(f'cannot set property "{name}" in multiple fibers')
        impl.value = value

        if hasattr(ctx, "_services"):
            ctx._services[name] = value
            setattr(ctx, name, value)
            ctx._service_attributes[name] = impl
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

            if key in self.store:
                raise RuntimeError(
                    f"service '{name}' has been registered at <{self.store[key].fiber.name}>"
                )
            self.store[key] = impl
            if hasattr(target_ctx, "_services"):
                target_ctx._services[name] = value

            if fiber and hasattr(fiber, "store") and fiber.store is not None:
                fiber.store[name] = impl

            from dsh.cordis.fiber import FiberState
            if fiber and fiber.state == FiberState.ACTIVE:
                self.notify([name], target_ctx)

            async def teardown() -> None:
                attribute_owners = getattr(target_ctx, "_service_attributes", {})
                if attribute_owners.get(name) is impl:
                    target_ctx.__dict__.pop(name, None)
                    del attribute_owners[name]
                if self.store.get(key) is not impl:
                    return
                del self.store[key]
                if hasattr(target_ctx, "_services") and name in target_ctx._services:
                    del target_ctx._services[name]
                affected = self.notify([name], target_ctx)
                if affected:
                    import asyncio
                    await asyncio.gather(*(fiber.wait() for fiber in affected))
                # Preserve provider self-access until dependent cleanup settles.
                if fiber and hasattr(fiber, "store") and fiber.store is not None:
                    if fiber.store.get(name) is impl:
                        del fiber.store[name]

            return teardown

        if hasattr(target_ctx, "effect"):
            return target_ctx.effect(setup, label=f"ctx.provide('{name}')")
        else:
            teardown_fn = setup()
            return teardown_fn

    def notify(self, names: List[str], source_ctx: Any = None) -> List[Any]:
        """
        Re-evaluate every fiber that requires one of the given services.
        """
        source_ctx = source_ctx or self.ctx
        affected_fibers: List[Any] = []
        if hasattr(self.ctx, "registry") and hasattr(self.ctx.registry, "update_dependencies"):
            affected_fibers = self.ctx.registry.update_dependencies(names, source_ctx)

        if hasattr(source_ctx, "emit"):
            for name in names:
                impl = self._get_impl(source_ctx, name, strict=False)
                val = impl.value if impl else None
                source_key = getattr(source_ctx, "_isolated_keys", {}).get(
                    name, name
                )
                event_ctx = source_ctx.extend()
                event_ctx._event_filter = lambda target, service=name, key=source_key: (
                    getattr(target, "_isolated_keys", {}).get(service, service)
                    == key
                )
                event_ctx.emit("internal/service", name, val)
        return affected_fibers

    def accessor(self, name: str, options: Dict[str, Any], ctx: Any = None) -> Callable[[], None]:
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

        target_ctx = ctx or self.ctx
        if hasattr(target_ctx, "effect"):
            return target_ctx.effect(setup, label=f"ctx.accessor('{name}')")
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
