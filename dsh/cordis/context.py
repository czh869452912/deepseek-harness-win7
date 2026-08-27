"""
Cordis Context matching reference/vendor/cordis/src/context.ts
Root and child dependency containers for Cordis plugins.
"""

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Set, Union

from dsh.cordis.events import EventBus
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.reflect import ReflectService
from dsh.cordis.registry import RegistryService
from dsh.cordis.plugin import Plugin


class Context:
    """
    Cordis Context: core dependency container for services, events, plugins,
    scoped hierarchies, lifecycle Fibers, isolated realms, and reversible effects.
    """

    def __init__(self, parent: Optional["Context"] = None, is_extension: bool = False):
        self._parent: Optional["Context"] = parent
        self._services: Dict[str, Any] = {}
        self._service_attributes: Dict[str, Any] = {}
        self._isolated_keys: Dict[str, Any] = {}
        self._intercept_map: Dict[str, Any] = {}
        self._own_intercepts: Dict[str, Any] = {}
        if parent is not None:
            self._event_bus: EventBus = parent._event_bus
            self.registry: RegistryService = parent.registry
            self.reflect: ReflectService = parent.reflect
            self.fiber: Fiber = parent.fiber
        else:
            self._event_bus = EventBus()
            self.reflect = ReflectService(self)
            self.registry = RegistryService(self)
            self.fiber = Fiber(self, None, config={}, runtime=None)
            self.reflect.setup_mixins()

    @property
    def root(self) -> "Context":
        curr = self
        while curr._parent is not None:
            curr = curr._parent
        return curr

    @property
    def events(self) -> EventBus:
        return self._event_bus

    def set_service(self, name: str, service_instance: Any) -> None:
        """
        Bind a service instance to context (or root if not isolated) and trigger dependency resolution & events.
        """
        self.reflect.provide(self, name, service_instance)

    def provide(self, name: str, service_instance: Any = None, check: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
        """
        Register a service implementation owned by the current fiber.
        """
        return self.reflect.provide(self, name, service_instance, check=check)

    def accessor(self, name: str, options: Dict[str, Any]) -> Callable[[], None]:
        """Define an accessor owned by the fiber on this context."""
        return self.reflect.accessor(name, options, ctx=self)

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
        return self.reflect._get_impl(self, name, strict=True) is not None

    def effect(self, setup_or_disposer: Any, label: str = "") -> Callable[[], None]:
        """
        Register a reversible effect setup/cleanup function on this context's fiber.
        """
        return self.fiber.effect(setup_or_disposer, label=label)

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register an event handler and track its disposer as a fiber effect.
        """
        return self.effect(
            lambda: self._event_bus.on(
                event_name,
                handler,
                prepend=prepend,
                global_listener=global_listener,
                ctx=self,
            ),
            label=f"ctx.on({event_name})",
        )

    def once(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register a single-shot event handler and track its disposer as a fiber effect.
        """
        raw_disposer: Optional[Callable[[], Any]] = None
        effect_disposer: Optional[Callable[[], Any]] = None

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if raw_disposer is not None:
                raw_disposer()
            if effect_disposer is not None:
                pending = effect_disposer()
                if inspect.iscoroutine(pending):
                    pending.close()
            return handler(*args, **kwargs)

        def setup() -> Callable[[], Any]:
            nonlocal raw_disposer
            raw_disposer = self._event_bus.on(
                event_name,
                wrapped,
                prepend=prepend,
                global_listener=global_listener,
                ctx=self,
            )
            return raw_disposer

        effect_disposer = self.effect(setup, label=f"ctx.once({event_name})")
        return effect_disposer

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        kwargs["caller_ctx"] = self
        self._event_bus.emit(event_name, *args, **kwargs)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        kwargs["caller_ctx"] = self
        await self._event_bus.emit_async(event_name, *args, **kwargs)

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["caller_ctx"] = self
        return await self._event_bus.waterfall(event_name, data, *args, **kwargs)

    def waterfall_sync(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["caller_ctx"] = self
        return self._event_bus.waterfall_sync(event_name, data, *args, **kwargs)

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        kwargs["caller_ctx"] = self
        return await self._event_bus.parallel(event_name, *args, **kwargs)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs["caller_ctx"] = self
        return await self._event_bus.serial(event_name, *args, **kwargs)

    async def bail(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs["caller_ctx"] = self
        return await self._event_bus.bail(event_name, *args, **kwargs)

    def bail_sync(self, event_name: str, *args: Any, **kwargs: Any) -> Any:
        kwargs["caller_ctx"] = self
        return self._event_bus.bail_sync(event_name, *args, **kwargs)

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Optional[Plugin]:
        """
        Load a plugin onto context wrapped in a Fiber.
        """
        fiber = self.registry.plugin(plugin_cls_or_instance, config=config, parent_ctx=self)
        return fiber.plugin if fiber else None

    def inject(self, deps: Any, callback: Callable[..., Any]) -> Any:
        """
        Run a callback once requested services are available.
        Shorthand for ctx.plugin({ inject, apply: callback }).
        """
        return self.registry.inject(deps, callback, parent_ctx=self)

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
            })
        return result

    def extend(self, meta: Optional[Dict[str, Any]] = None) -> "Context":
        """
        Create a child context inheriting services and event bus.
        """
        child = Context(parent=self, is_extension=True)
        child._isolated_keys = dict(self._isolated_keys)
        child._intercept_map = dict(self._intercept_map)
        if meta:
            for k, v in meta.items():
                setattr(child, k, v)
        return child

    def isolate(self, name_or_keys: Union[str, List[str], Dict[str, Any]] = None, label: Any = None, keys: Optional[List[str]] = None) -> "Context":
        """
        Create a child context isolated from parent for specific service keys.
        """
        child = self.extend()
        target_keys = keys if keys is not None else name_or_keys
        if isinstance(target_keys, str):
            child._isolated_keys[target_keys] = label or object()
        elif isinstance(target_keys, list):
            for k in target_keys:
                child._isolated_keys[k] = label or object()
        elif isinstance(target_keys, dict):
            for k, v in target_keys.items():
                child._isolated_keys[k] = v
        return child

    def intercept(self, name: str, config: Any) -> "Context":
        """
        Add service-specific intercept config for plugins loaded below this context.
        """
        child = self.extend()
        child._intercept_map[name] = config
        child._own_intercepts[name] = config
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

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in ("registry", "reflect", "fiber", "root", "events", "props", "store"):
            raise AttributeError(f"Context object has no attribute '{name}'")
        if hasattr(self, "reflect"):
            return self.reflect.get_property(self, name)
        raise AttributeError("Context object has no attribute or service '%s'" % name)
