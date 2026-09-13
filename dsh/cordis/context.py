"""
Cordis Context matching reference/vendor/cordis/src/context.ts
Root and child dependency containers for Cordis plugins.
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Union

from dsh.cordis.events import EventBus
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.logger import LoggerService
from dsh.cordis.reflect import ReflectService
from dsh.cordis.registry import RegistryService
from dsh.cordis.plugin import Plugin


class Context:
    """
    Cordis Context: core dependency container for services, events, plugins,
    scoped hierarchies, lifecycle Fibers, isolated realms, and reversible effects.
    Matching reference/vendor/cordis/src/context.ts.
    """

    __cordis_context_brand__: str = "cordis.v1.context"
    effect_symbol: str = "symbols.effect"
    filter_symbol: str = "symbols.filter"
    isolate_symbol: str = "symbols.isolate"
    intercept_symbol: str = "symbols.intercept"
    isolate: str = "symbols.isolate"
    intercept: str = "symbols.intercept"

    @classmethod
    def is_(cls, value: Any) -> bool:
        """
        Check whether value is a Cordis Context matching TS Context.is(value).
        Uses global immutable brand identifier to work across realms and module reloads.
        """
        if value is None:
            return False
        return getattr(value, "__cordis_context_brand__", None) == "cordis.v1.context"

    @classmethod
    def is_context(cls, value: Any) -> bool:
        """Alias for Context.is_ matching TS Context.is."""
        return cls.is_(value)

    def __repr__(self) -> str:
        fiber = self.__dict__.get("fiber") or getattr(self, "_fiber", None)
        name = getattr(fiber, "name", None) if fiber else "root"
        return f"Context <{name or 'root'}>"

    def __init__(
        self,
        parent: Optional["Context"] = None,
        is_extension: bool = False,
        strict_inject: Optional[bool] = None,
        base_url: Optional[str] = None,
    ):
        self._parent: Optional["Context"] = parent
        self._services: Dict[str, Any] = {}
        self._isolated_keys: Dict[str, Any] = {}
        self._intercept_map: Dict[str, Any] = {}
        self._effects: List[Callable[[], Any]] = []
        self._baseUrl: Optional[str] = base_url or (getattr(parent, "baseUrl", None) if parent else None)
        self.base_url: Optional[str] = self._baseUrl

        if strict_inject is not None:
            self.strict_inject: bool = strict_inject
        elif parent is not None and hasattr(parent, "strict_inject"):
            self.strict_inject = parent.strict_inject
        else:
            import os
            self.strict_inject = os.environ.get("DSH_STRICT_INJECT", "1") not in ("0", "false", "False")

        if parent is not None:
            self._event_bus: EventBus = parent._event_bus
            self.registry: RegistryService = parent.registry._bind(self) if hasattr(parent.registry, "_bind") else parent.registry
            self.reflect: ReflectService = parent.reflect._bind(self) if hasattr(parent.reflect, "_bind") else parent.reflect
            self.fiber: Fiber = parent.fiber
            self.logger: LoggerService = parent.logger._bind(self) if hasattr(parent.logger, "_bind") else parent.logger
            self.timer: Any = getattr(parent, "timer", None)
        else:
            self._event_bus = EventBus(ctx=self)
            self.reflect = ReflectService(self)
            self.registry = RegistryService(self)
            self.fiber = Fiber(self, None, config={}, runtime=None)
            self.logger = LoggerService(self)
            from dsh.cordis.timer import TimerService
            self.timer = TimerService(self)
            self.reflect.setup_mixins()
            self.fiber._disposables.clear()

    @property
    def parent(self) -> Optional["Context"]:
        return self._parent

    @parent.setter
    def parent(self, val: Optional["Context"]) -> None:
        self._parent = val

    @property
    def root(self) -> "Context":
        curr = self
        while curr._parent is not None:
            curr = curr._parent
        return curr

    @property
    def events(self) -> EventBus:
        return self._event_bus

    def set_service(self, name: str, service_instance: Any, check: Optional[Callable[[], bool]] = None) -> None:
        """
        Bind a service instance to context (or root if not isolated) and trigger dependency resolution & events.
        """
        target = self if name in self._isolated_keys else self.root
        target._services[name] = service_instance
        setattr(target, name, service_instance)

        chk = check
        if chk is None:
            if hasattr(service_instance, "_check_availability") and callable(service_instance._check_availability):
                chk = service_instance._check_availability
            elif hasattr(service_instance, "check") and callable(service_instance.check):
                chk = service_instance.check

        from dsh.cordis.utils import get_isolate_symbol
        key = get_isolate_symbol(self, name) or (getattr(self.root, "_isolated_keys", {}).get(name) if hasattr(self, "root") else name)
        if hasattr(self, "reflect") and hasattr(self.reflect, "store"):
            if key in self.reflect.store:
                impl = self.reflect.store[key]
                if chk is not None:
                    impl.check = chk
                if impl.value is service_instance and chk is None:
                    return
                impl.value = service_instance
                self.reflect.notify([name])
                return

        self.reflect.provide(self, name, service_instance, check=chk, allow_replace=True)

    def provide(self, name: str, service_instance: Any = None, check: Optional[Callable[[], bool]] = None, allow_replace: bool = False) -> Callable[[], None]:
        """
        Register a service implementation owned by the current fiber.
        """
        return self.reflect.provide(self, name, service_instance, check=check, allow_replace=allow_replace)

    def get_service(self, name: str, default: Any = None) -> Any:
        """
        Get service instance by name from this context or parent hierarchy, respecting isolate maps.
        """
        if name in self._services:
            return self._services[name]

        isolated_label = self._isolated_keys.get(name)
        if self._parent is not None and isolated_label is None:
            return self._parent.get_service(name, default)
        return default

    def get(self, name: str, strict: bool = True, default: Any = None) -> Any:
        """
        Read a service or property from context via reflect layer.

        The second parameter is `strict`, matching reflect.ts
        `get(name, strict = true)`, so a positional second argument cannot
        silently turn into a default value.
        """
        return self.reflect.get(self, name, strict=strict, default=default)

    def set(self, name: str, value: Any) -> bool:
        """
        Overwrite a provided service or property value on context via reflect layer matching TS ctx[key] = val.
        """
        return self.reflect.set(self, name, value)

    def has(self, name: str) -> bool:
        """
        Check whether a service or accessor property is declared in this context scope matching TS Reflect.has / handler.has.
        """
        if hasattr(self, "reflect") and self.reflect:
            if hasattr(self.reflect, "props") and name in self.reflect.props:
                return True
            isolated_map = getattr(self, "_isolated_keys", {})
            key = isolated_map.get(name, name)
            if hasattr(self.reflect, "store") and (key in self.reflect.store or name in self.reflect.store):
                return True
        curr = self
        while curr is not None:
            if hasattr(curr, "_services") and name in curr._services:
                return True
            curr = getattr(curr, "_parent", None)
        return False

    def effect(self, setup_or_disposer: Any, label: Optional[str] = None) -> Callable[[], None]:
        """
        Register a reversible effect setup/cleanup function.
        Delegates to current fiber effect matching TS context.effect(); an omitted
        label keeps the fiber default.
        """
        if self.fiber:
            if label is None:
                return self.fiber.effect(setup_or_disposer)
            return self.fiber.effect(setup_or_disposer, label=label)
        raise RuntimeError("cannot register effect on context without fiber")

    def disposable(self, disposer: Callable[[], Any], label: str = "") -> Callable[[], None]:
        """Register a pre-existing teardown/disposer function directly as a fiber effect."""
        if self.fiber:
            return self.fiber.effect(disposer, label=label, is_disposer=True)
        raise RuntimeError("cannot register disposable on context without fiber")

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register an event handler and track its disposer as a fiber effect.
        """
        if self.fiber:
            self.fiber.assert_active()
        return self._event_bus.on(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)

    def once(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register a single-shot event handler and track its disposer as a fiber effect.
        """
        if self.fiber:
            self.fiber.assert_active()
        return self._event_bus.once(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("caller_ctx", self)
        self._event_bus.emit(event_name, *args, **kwargs)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("caller_ctx", self)
        await self._event_bus.emit_async(event_name, *args, **kwargs)

    async def waterfall(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.waterfall(event_name, *args, **kwargs)

    def waterfall_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return self._event_bus.waterfall_sync(event_name, *args, **kwargs)

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Dispatch an event to every listener concurrently matching TS EventBus.parallel."""
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.parallel(event_name, *args, **kwargs)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.serial(event_name, *args, **kwargs)

    def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        """Dispatch an event synchronously until a listener bails matching TS EventBus.bail."""
        kwargs.setdefault("caller_ctx", self)
        return self._event_bus.bail(event_name, *args, **kwargs)

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Any:
        """
        Load a plugin onto context wrapped in a Fiber matching TS ctx.plugin().
        Returns the Fiber instance (which is awaitable and transparently delegates attribute access to plugin).
        """
        fiber = self.registry.plugin(plugin_cls_or_instance, config=config, parent_ctx=self)
        return fiber

    def inject(self, deps: Any, callback: Callable[..., Any]) -> Any:
        """
        Run a callback once requested services are available.
        Shorthand for ctx.plugin({ inject, apply: callback }).
        """
        return self.registry.inject(deps, callback)

    def unload_plugin(self, plugin_id: str) -> bool:
        """
        Unload a plugin by id.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.registry.unload_plugin(plugin_id))
            return True
        except RuntimeError:
            return asyncio.run(self.registry.unload_plugin(plugin_id))

    def list_plugins(self) -> List[Dict[str, Any]]:
        """
        Return metadata for loaded plugins.
        """
        result = []
        for fiber in self.registry.list_fibers():
            plugin = fiber.plugin
            result.append({
                "id": getattr(plugin, "id", fiber.name),
                "name": getattr(plugin, "name", fiber.name),
                "class": plugin.__class__.__name__ if plugin else "FunctionPlugin",
                "inject": getattr(plugin, "inject", []),
                "config": getattr(plugin, "config", getattr(fiber, "config", {})),
                "state": fiber.state,
                "epoch": getattr(fiber, "epoch", ""),
            })
        return result

    @property
    def baseUrl(self) -> Optional[str]:
        if getattr(self, "_baseUrl", None) is not None:
            return self._baseUrl
        if getattr(self, "base_url", None) is not None:
            return self.base_url
        if getattr(self, "_parent", None) is not None:
            return getattr(self._parent, "baseUrl", None)
        return None

    @baseUrl.setter
    def baseUrl(self, value: Optional[str]) -> None:
        self._baseUrl = value
        self.base_url = value

    def extend(self, meta: Optional[Dict[str, Any]] = None) -> "Context":
        """
        Create a child context inheriting services and event bus.
        """
        child = Context(parent=self, is_extension=True, strict_inject=self.strict_inject, base_url=self.baseUrl)
        child._isolated_keys = dict(self._isolated_keys)
        # TS `extend()` inherits the parent's intercept map through the context
        # prototype chain, so the child starts with no entry of its own; readers
        # walk `_parent` for the ancestors' levels. Copying the parent map here
        # would replay every ancestor entry a second time and hide overrides.
        shadow = getattr(self, "_shadow", None)
        if shadow is not None:
            child._shadow = shadow
        if meta:
            for k, v in meta.items():
                setattr(child, k, v)
        return child

    def isolate(self, name: Optional[Union[str, List[str]]] = None, label: Any = None, **kwargs: Any) -> "Context":
        """
        Create a child context isolated from parent for a specific service key matching TS Context.isolate.
        """
        keys = kwargs.get("keys")
        if keys is not None:
            name_list = keys
        elif isinstance(name, list):
            name_list = name
        elif isinstance(name, str):
            name_list = [name]
        else:
            name_list = []

        shadow = dict(self._isolated_keys)
        for k in name_list:
            shadow[k] = label if label is not None else object()
        child = self.extend()
        child._isolated_keys = shadow
        return child

    def intercept(self, name: str, config: Any) -> "Context":
        """
        Add service-specific intercept config for plugins loaded below this context.
        """
        child = self.extend()
        child._intercept_map[name] = config
        return child

    def teardown(self) -> None:
        """
        Teardown context effects in reverse order.

        A root context's teardown owns no parent registration to drive it,
        so the fiber owns the settlement: `await_settled()` and
        `settle_fibers()` then join it instead of leaving a scheduled task
        that dies with the loop.
        """
        if self._parent is None and self.fiber:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self.fiber.dispose())
            else:
                self.fiber.schedule_settlement(self.fiber.dispose())

        if self._effects:
            self._effects.clear()

    dispose = teardown

    def timeout(self, callback_or_delay: Any, delay_ms: Optional[Union[float, int]] = None) -> Any:
        """Run a callback once or return a Future after delay_ms matching TS ctx.timeout()."""
        if hasattr(self, "timer") and self.timer is not None:
            return self.timer.timeout(callback_or_delay, delay_ms, ctx=self)
        raise RuntimeError("TimerService is not available on Context")

    def interval(self, callback_or_delay: Any, delay_ms: Optional[Union[float, int]] = None) -> Any:
        """Run a callback repeatedly or return an AsyncIterator matching TS ctx.interval()."""
        if hasattr(self, "timer") and self.timer is not None:
            return self.timer.interval(callback_or_delay, delay_ms, ctx=self)
        raise RuntimeError("TimerService is not available on Context")

    def throttle(self, callback: Callable[..., Any], delay_ms: float, no_trailing: bool = False) -> Callable[..., Any]:
        """Return a throttled function matching TS ctx.throttle()."""
        if hasattr(self, "timer") and self.timer is not None:
            return self.timer.throttle(callback, delay_ms, no_trailing=no_trailing, ctx=self)
        raise RuntimeError("TimerService is not available on Context")

    def debounce(self, callback: Callable[..., Any], delay_ms: float) -> Callable[..., Any]:
        """Return a debounced function matching TS ctx.debounce()."""
        if hasattr(self, "timer") and self.timer is not None:
            return self.timer.debounce(callback, delay_ms, ctx=self)
        raise RuntimeError("TimerService is not available on Context")

    def setTimeout(self, callback: Callable[[], Any], delay_ms: float) -> Callable[[], None]:
        return self.timeout(callback, delay_ms)

    def setInterval(self, callback: Callable[[], Any], delay_ms: float) -> Callable[[], None]:
        return self.interval(callback, delay_ms)

    def __getattr__(self, name: str) -> Any:
        RESERVED_ATTRS = (
            "registry", "reflect", "fiber", "entry", "root", "events", "props", "store", "logger", "timer",
            "symbols", "base_url", "baseUrl", "strict_inject", "scope", "is_shadow", "_shadow", "_shadow_fiber",
        )
        if name.startswith("_") or name.startswith("cordis.") or name.startswith("symbols.") or name in RESERVED_ATTRS or name.isdigit():
            raise AttributeError(f"Context object has no attribute '{name}'")

        # 1. Accessor check matching TS def?.type === 'accessor'
        err = RuntimeError(f'cannot get property "{name}" without inject')
        if hasattr(self, "reflect") and self.reflect and hasattr(self.reflect, "props"):
            def_prop = self.reflect.props.get(name)
            if def_prop and getattr(def_prop, "type", None) == "accessor":
                from dsh.cordis.utils import Symbols
                receiver = getattr(self, Symbols.receiver, self)
                return def_prop.get(receiver, err)

        # 2. Strict Dependency Injection Enforcement matching TS Cordis ReflectService.handler:152-167
        # TS reflect.ts:152: if (!ctx.fiber.runtime) return ctx.reflect.get(prop, false)
        if getattr(self, "fiber", None) and getattr(self.fiber, "runtime", None) is None:
            if hasattr(self, "reflect") and hasattr(self.reflect, "get"):
                val = self.reflect.get(self, name, default=None, strict=False)
                if val is not None:
                    from dsh.cordis.utils import get_traceable
                    return get_traceable(self, val)
            raise AttributeError(f"Context object has no attribute or service '{name}'")

        if getattr(self, "fiber", None) is not None and getattr(self.fiber, "runtime", None) is not None and not getattr(self, "strict_inject", True):
            # Plugin-fiber context without strict injection: the reference proxy
            # dispatches `internal/get` for every fiber-owned context.
            def _resolve_loose():
                val = self.reflect.get(self, name, default=None, strict=False)
                if val is not None:
                    from dsh.cordis.utils import get_traceable
                    return get_traceable(self, val)
                raise AttributeError(f"Context object has no attribute or service '{name}'")

            if hasattr(self, "waterfall_sync"):
                return self.waterfall_sync("internal/get", self, name, err, _resolve_loose)
            return _resolve_loose()

        if getattr(self, "strict_inject", True) and getattr(self, "fiber", None) and self.fiber.runtime is not None:
            def _resolve_strict():
                curr_fiber = getattr(self, "_shadow_fiber", None) or self.fiber
                from dsh.cordis.utils import get_isolate_symbol
                key = get_isolate_symbol(self, name) or getattr(self, "_isolated_keys", {}).get(name, name)
                while curr_fiber is not None:
                    store = getattr(curr_fiber, "store", None)
                    impl = None
                    if store:
                        impl = store.get(key) or store.get(name)
                    if impl is not None:
                        from dsh.cordis.utils import get_traceable
                        val = getattr(impl, "value", impl)
                        return get_traceable(self, val)
                    if name in getattr(curr_fiber, "inject", {}):
                        raise RuntimeError(f'cannot get required service "{name}" in inactive context')
                    if not getattr(curr_fiber, "runtime", None):
                        raise err
                    parent_ctx = getattr(curr_fiber, "parent", None)
                    if not parent_ctx:
                        raise err
                    parent_key = get_isolate_symbol(parent_ctx, name) or getattr(parent_ctx, "_isolated_keys", {}).get(name, name)
                    if parent_key != key:
                        raise err
                    curr_fiber = getattr(parent_ctx, "fiber", None)
                raise err

            if hasattr(self, "waterfall_sync"):
                return self.waterfall_sync("internal/get", self, name, err, _resolve_strict)
            return _resolve_strict()

        if hasattr(self, "reflect"):
            val = self.reflect.get(self, name, default=None, strict=False)
            if val is not None:
                from dsh.cordis.utils import get_traceable
                return get_traceable(self, val)
        raise AttributeError(f"Context object has no attribute or service '{name}'")

    def __getitem__(self, item: Any) -> Any:
        if item is Context.isolate or item == getattr(Context, "isolate_symbol", "symbols.isolate") or item == "symbols.isolate":
            return IsolatedKeysView(self._isolated_keys)
        if item == getattr(Context, "intercept_symbol", "symbols.intercept") or item == "symbols.intercept":
            return getattr(self, "_intercept_map", {})
        raise KeyError(item)


class IsolatedKeysView(dict):
    """Dictionary supporting attribute access matching JS isolate object."""
    def __getattr__(self, name: str) -> Any:
        return self.get(name)
