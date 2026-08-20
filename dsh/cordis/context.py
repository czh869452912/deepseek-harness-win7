import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Set, Type
from dsh.cordis.events import EventBus
from dsh.cordis.plugin import Plugin


class Context:
    """
    Cordis Context: core container for services, events, plugins, and reversible effects.
    """

    def __init__(self, parent: Optional['Context'] = None):
        self._parent = parent
        self._services: Dict[str, Any] = {}
        self._plugins: Dict[str, Plugin] = {}
        self._effects: List[Callable[[], None]] = []
        self._event_bus = parent._event_bus if parent else EventBus()
        self._isolated_keys: Set[str] = set()

    def set_service(self, name: str, service_instance: Any) -> None:
        """
        Bind a service instance to context (e.g., ctx.set_service('tools', tools_service)).
        """
        self._services[name] = service_instance
        setattr(self, name, service_instance)

    def get_service(self, name: str, default: Any = None) -> Any:
        """
        Get service instance by name from this context or parent.
        """
        if name in self._services:
            return self._services[name]
        if self._parent and name not in self._isolated_keys:
            return self._parent.get_service(name, default)
        return default

    def get(self, name: str, default: Any = None) -> Any:
        return self.get_service(name, default)

    def has(self, name: str) -> bool:
        return name in self._services or (self._parent is not None and self._parent.has(name))

    def effect(self, cleanup_func: Callable[[], None]) -> None:
        """
        Register a reversible effect cleanup function (disposer).
        """
        self._effects.append(cleanup_func)

    def on(self, event_name: str, handler: Callable[..., Any], prepend: bool = False) -> Callable[[], None]:
        """
        Register an event handler and track its disposer as a context effect.
        """
        disposer = self._event_bus.on(event_name, handler, prepend=prepend)
        self.effect(disposer)
        return disposer

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        self._event_bus.emit(event_name, *args, **kwargs)

    async def emit_async(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        await self._event_bus.emit_async(event_name, *args, **kwargs)

    async def waterfall(self, event_name: str, data: Any, *args: Any, **kwargs: Any) -> Any:
        return await self._event_bus.waterfall(event_name, data, *args, **kwargs)

    async def parallel(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        return await self._event_bus.parallel(event_name, *args, **kwargs)

    async def serial(self, event_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        return await self._event_bus.serial(event_name, *args, **kwargs)

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Optional[Plugin]:
        """
        Mount a plugin into this context.
        """
        if isinstance(plugin_cls_or_instance, Plugin):
            plugin = plugin_cls_or_instance
            if config:
                plugin.config.update(config)
        elif inspect.isclass(plugin_cls_or_instance) and issubclass(plugin_cls_or_instance, Plugin):
            plugin = plugin_cls_or_instance(config=config)
        elif callable(plugin_cls_or_instance):
            # Function-style plugin: apply(ctx)
            plugin_cls_or_instance(self)
            return None
        else:
            raise ValueError(f"Invalid plugin type: {plugin_cls_or_instance}")

        plugin_id = plugin.id or plugin.__class__.__name__

        # Check inject dependencies
        for dep in plugin.inject:
            if not self.has(dep):
                print(f"[Cordis Loader Warning] Plugin '{plugin_id}' waiting for dependency service '{dep}'")

        plugin.ctx = self
        plugin.apply(self)
        self._plugins[plugin_id] = plugin

        def plugin_disposer():
            plugin.teardown()

        self.effect(plugin_disposer)
        return plugin

    def unload_plugin(self, plugin_id: str) -> bool:
        """
        Unload a plugin by id.
        """
        if plugin_id in self._plugins:
            plugin = self._plugins.pop(plugin_id)
            plugin.teardown()
            return True
        return False

    def list_plugins(self) -> List[Dict[str, Any]]:
        """
        Return metadata for loaded plugins.
        """
        result = []
        for pid, plugin in self._plugins.items():
            result.append({
                "id": pid,
                "name": plugin.name or pid,
                "class": plugin.__class__.__name__,
                "inject": plugin.inject,
                "config": plugin.config
            })
        return result

    def isolate(self, keys: Optional[List[str]] = None) -> 'Context':
        """
        Create a child context isolated from parent for specific service keys.
        """
        child = Context(parent=self)
        if keys:
            child._isolated_keys.update(keys)
        return child

    def teardown(self) -> None:
        """
        Teardown context by executing all cleanup effects in reverse order.
        """
        while self._effects:
            effect_func = self._effects.pop()
            try:
                effect_func()
            except Exception as e:
                print(f"[Cordis Teardown Error] Exception in effect cleanup: {e}")

    def __getattr__(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        if self._parent and name not in self._isolated_keys and hasattr(self._parent, name):
            return getattr(self._parent, name)
        raise AttributeError(f"Context object has no attribute or service '{name}'")
