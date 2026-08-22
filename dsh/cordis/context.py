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
    Cordis Context: core container for services, events, plugins, scoped hierarchies,
    lifecycle Fibers, isolated realms, and reversible effects.
    """

    def __init__(self, parent: Optional["Context"] = None):
        self._parent: Optional["Context"] = parent
        self._services: Dict[str, Any] = {}
        self._isolated_keys: Dict[str, Any] = {}
        self._intercept_map: Dict[str, Any] = {}
        self._effects: List[Callable[[], Any]] = []

        if parent:
            self._event_bus: EventBus = parent._event_bus
            self.registry: RegistryService = parent.registry
            self.reflect: ReflectService = parent.reflect
            self.fiber: Fiber = Fiber(self, self, config={})
            self.fiber.state = FiberState.ACTIVE
        else:
            self._event_bus = EventBus()
            self.reflect = ReflectService(self)
            self.registry = RegistryService(self)
            self.fiber = Fiber(self, self, config={})
            self.fiber.state = FiberState.ACTIVE

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
        Bind a service instance to context and trigger dependency resolution & events.
        """
        self._services[name] = service_instance
        setattr(self, name, service_instance)
        self.reflect.on_set(self, name, service_instance)
        self.registry.update_dependencies()

    def provide(self, name: str, service_instance: Any) -> None:
        self.set_service(name, service_instance)

    def get_service(self, name: str, default: Any = None) -> Any:
        """
        Get service instance by name from this context or parent hierarchy, respecting isolate maps.
        """
        if name in self._services:
            return self._services[name]
        if self._parent is not None and name not in self._isolated_keys:
            return self._parent.get_service(name, default)
        return default

    def get(self, name: str, default: Any = None) -> Any:
        return self.reflect.get(self, name, default)

    def has(self, name: str) -> bool:
        return name in self._services or (self._parent is not None and name not in self._isolated_keys and self._parent.has(name))

    def effect(self, setup_or_disposer: Any, label: str = "") -> Callable[[], None]:
        """
        Register a reversible effect setup/cleanup function.
        Delegates to current fiber effect if active, or tracks as context effect.
        """
        if self.fiber and self.fiber.state in (FiberState.ACTIVE, FiberState.LOADING):
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
            except Exception:
                pass

        return cancel_effect

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        """
        Register an event handler and track its disposer as a context effect.
        """
        disposer = self._event_bus.on(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)
        self.effect(disposer, label=f"ctx.on({event_name})")
        return disposer

    def once(self, event_name: str, handler: Callable[..., Any], prepend: bool = False, global_listener: bool = False) -> Callable[[], None]:
        disposer = self._event_bus.once(event_name, handler, prepend=prepend, global_listener=global_listener, ctx=self)
        self.effect(disposer, label=f"ctx.once({event_name})")
        return disposer

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
        Mount a plugin onto context. Delegates to RegistryService for Fiber wrapping and inject resolution.
        """
        fiber = self.registry.plugin(plugin_cls_or_instance, config=config)
        return fiber.plugin if fiber else None

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
                "class": plugin.__class__.__name__,
                "inject": getattr(plugin, "inject", []),
                "config": getattr(plugin, "config", {}),
                "state": fiber.state,
            })
        return result

    def extend(self, meta: Optional[Dict[str, Any]] = None) -> "Context":
        """
        Create a child scoped context inheriting services and event bus.
        """
        child = Context(parent=self)
        if meta:
            for k, v in meta.items():
                setattr(child, k, v)
        return child

    def isolate(self, name_or_keys: Union[str, List[str], Dict[str, Any]] = None, label: Any = None, keys: Optional[List[str]] = None) -> "Context":
        """
        Create a child context isolated from parent for specific service keys/labels.
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
        return child

    def teardown(self) -> None:
        """
        Teardown context by executing all cleanup effects in reverse order.
        """
        if self.fiber:
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

    def __getattr__(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        if self._parent and name not in self._isolated_keys and hasattr(self._parent, name):
            return getattr(self._parent, name)
        raise AttributeError(f"Context object has no attribute or service '{name}'")
