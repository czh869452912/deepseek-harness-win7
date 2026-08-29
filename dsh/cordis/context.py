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

    effect_symbol: str = "symbols.effect"
    filter_symbol: str = "symbols.filter"
    isolate_symbol: str = "symbols.isolate"
    intercept_symbol: str = "symbols.intercept"

    @classmethod
    def is_(cls, value: Any) -> bool:
        """Check whether value is a Cordis Context matching TS Context.is(value)."""
        return isinstance(value, Context) or (
            value is not None
            and hasattr(value, "registry")
            and hasattr(value, "reflect")
            and hasattr(value, "extend")
        )

    @classmethod
    def is_context(cls, value: Any) -> bool:
        """Alias for Context.is_ matching TS Context.is."""
        return cls.is_(value)

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
        self.base_url: Optional[str] = base_url or (parent.base_url if parent else None)
        self.baseUrl: Optional[str] = self.base_url

        if strict_inject is not None:
            self.strict_inject: bool = strict_inject
        elif parent is not None and hasattr(parent, "strict_inject"):
            self.strict_inject = parent.strict_inject
        else:
            import os
            self.strict_inject = os.environ.get("DSH_STRICT_INJECT", "1") not in ("0", "false", "False")

        if parent is not None:
            self._event_bus: EventBus = parent._event_bus
            self.registry: RegistryService = parent.registry
            self.reflect: ReflectService = parent.reflect
            self.fiber: Fiber = parent.fiber
            self.logger: LoggerService = parent.logger
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
            self.fiber._effect_metas.clear()

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

        self.reflect.provide(self, name, service_instance, check=chk, allow_replace=True)

    def provide(self, name: str, service_instance: Any = None, check: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
        """
        Register a service implementation owned by the current fiber.
        """
        return self.reflect.provide(self, name, service_instance, check=check)

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

    def get(self, name: str, default: Any = None, strict: bool = True) -> Any:
        """
        Read a service or property from context via reflect layer.
        """
        return self.reflect.get(self, name, default=default, strict=strict)

    def has(self, name: str) -> bool:
        """
        Check whether a service is available in this context scope.
        """
        return self.get(name, strict=False) is not None

    def effect(self, setup_or_disposer: Any, label: str = "") -> Callable[[], None]:
        """
        Register a reversible effect setup/cleanup function.
        Delegates to current fiber effect matching TS context.effect().
        """
        if self.fiber:
            return self.fiber.effect(setup_or_disposer, label=label)

        if not callable(setup_or_disposer):
            return lambda: None

        self._effects.append(setup_or_disposer)
        disposed = False

        def cancel_effect() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            if setup_or_disposer in self._effects:
                self._effects.remove(setup_or_disposer)
            try:
                res = setup_or_disposer()
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                if hasattr(self, "logger"):
                    self.logger("context").warn("Exception in cancel_effect '%s': %s", label, e)
                else:
                    sys.stderr.write(f"[Cordis Context Error] Exception in cancel_effect '{label}': {e}\n")

        return cancel_effect

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register an event handler and track its disposer as a fiber effect.
        """
        disposer = self._event_bus.on(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)
        self.effect(disposer, label=f"ctx.on({event_name})")
        return disposer

    def once(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register a single-shot event handler and track its disposer as a fiber effect.
        """
        disposer = self._event_bus.once(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)
        self.effect(disposer, label=f"ctx.once({event_name})")
        return disposer

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

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.parallel(event_name, *args, **kwargs)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.serial(event_name, *args, **kwargs)

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return await self._event_bus.bail(event_name, *args, **kwargs)

    def bail_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("caller_ctx", self)
        return self._event_bus.bail_sync(event_name, *args, **kwargs)

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Any:
        """
        Load a plugin onto context wrapped in a Fiber matching TS ctx.plugin().
        Returns the Fiber instance (which is awaitable and transparently delegates attribute access to plugin).
        """
        fiber = self.registry.plugin(plugin_cls_or_instance, config=config)
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

    def extend(self, meta: Optional[Dict[str, Any]] = None) -> "Context":
        """
        Create a child context inheriting services and event bus.
        """
        child = Context(parent=self, is_extension=True, strict_inject=self.strict_inject, base_url=self.base_url)
        child._isolated_keys = dict(self._isolated_keys)
        child._intercept_map = dict(self._intercept_map)
        if meta:
            for k, v in meta.items():
                setattr(child, k, v)
        return child

    def isolate(self, name_or_keys: Union[str, List[str], Dict[str, Any]] = None, label: Any = None, keys: Optional[List[str]] = None) -> "Context":
        """
        Create a child context isolated from parent for specific service keys matching TS Context.isolate.
        """
        shadow = dict(self._isolated_keys)
        target_keys = keys if keys is not None else name_or_keys
        if isinstance(target_keys, str):
            shadow[target_keys] = label or object()
        elif isinstance(target_keys, list):
            for k in target_keys:
                shadow[k] = label or object()
        elif isinstance(target_keys, dict):
            for k, v in target_keys.items():
                shadow[k] = v

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
        """
        if self._parent is None and self.fiber:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.fiber.dispose())
            except RuntimeError:
                asyncio.run(self.fiber.dispose())

        while self._effects:
            effect_func = self._effects.pop()
            try:
                res = effect_func()
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception:
                pass

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
            "registry", "reflect", "fiber", "root", "events", "props", "store", "logger", "timer",
            "filter", "validate", "status", "teardown", "symbols", "base_url", "baseUrl",
            "strict_inject", "session", "agent",
        )
        if name.startswith("_") or name in RESERVED_ATTRS:
            raise AttributeError(f"Context object has no attribute '{name}'")

        # 1. Accessor check matching TS def?.type === 'accessor'
        if hasattr(self, "reflect") and self.reflect and hasattr(self.reflect, "props"):
            def_prop = self.reflect.props.get(name)
            if def_prop and getattr(def_prop, "type", None) == "accessor":
                from dsh.cordis.utils import Symbols
                receiver = getattr(self, Symbols.receiver, self)
                err = RuntimeError(f"cannot get property '{name}' without inject")
                return def_prop.get(receiver, err)

        # 2. 1:1 Strict Dependency Injection Enforcement matching TS Cordis ReflectService.handler
        if getattr(self, "strict_inject", True) and getattr(self, "fiber", None) and getattr(self.fiber, "runtime", None) is not None:
            curr_fiber = getattr(self, "_shadow_fiber", None) or self.fiber
            key = getattr(self, "_isolated_keys", {}).get(name, name)
            while curr_fiber is not None and getattr(curr_fiber, "runtime", None) is not None:
                impl = getattr(curr_fiber, "store", {}).get(name) if getattr(curr_fiber, "store", None) else None
                if impl is not None:
                    from dsh.cordis.utils import get_traceable
                    val = getattr(impl, "value", impl)
                    return get_traceable(self, val)
                if name in getattr(curr_fiber, "inject", {}):
                    raise RuntimeError(f"cannot get required service '{name}' in inactive context")
                parent_ctx = getattr(curr_fiber, "parent", None)
                if not parent_ctx:
                    break
                parent_key = getattr(parent_ctx, "_isolated_keys", {}).get(name, name)
                if parent_key != key:
                    break
                curr_fiber = getattr(parent_ctx, "fiber", None)
            raise RuntimeError(f"cannot get property '{name}' without inject")

        if name in self._services:
            from dsh.cordis.utils import get_traceable
            return get_traceable(self, self._services[name])
        if hasattr(self, "reflect"):
            val = self.reflect.get(self, name, default=None, strict=False)
            if val is not None:
                from dsh.cordis.utils import get_traceable
                return get_traceable(self, val)
        if self._parent and name not in self._isolated_keys and hasattr(self._parent, name):
            return getattr(self._parent, name)
        raise AttributeError(f"Context object has no attribute or service '{name}'")
