import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Set
from dsh.cordis.fiber import Fiber, FiberState, resolve_config


class RegistryService:
    """
    Plugin registry service for Cordis.
    Manages active and pending plugin Fibers, dynamic dependency injection,
    and automatic re-evaluation of pending plugins when services arrive or unload.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._fibers: Dict[str, Fiber] = {}
        self._pending_fibers: Set[Fiber] = set()
        self._updating = False

    def get_fiber(self, plugin_id: str) -> Optional[Fiber]:
        return self._fibers.get(plugin_id)

    def list_fibers(self) -> List[Fiber]:
        return list(self._fibers.values())

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Fiber:
        """
        Mount a plugin onto context wrapped in a Fiber.
        Evaluates dependencies: if dependencies are met, loads immediately; otherwise marks PENDING.
        """
        from dsh.cordis.plugin import Plugin

        if isinstance(plugin_cls_or_instance, Plugin):
            plugin = plugin_cls_or_instance
            if config:
                plugin.config.update(config)
        elif inspect.isclass(plugin_cls_or_instance) and issubclass(plugin_cls_or_instance, Plugin):
            plugin = plugin_cls_or_instance(config=config)
        elif callable(plugin_cls_or_instance):
            # Function plugin wrapper
            class FuncPlugin(Plugin):
                def apply(self, c: Any) -> None:
                    plugin_cls_or_instance(c, config)
            plugin = FuncPlugin(config=config)
        else:
            raise ValueError(f"Invalid plugin type: {plugin_cls_or_instance}")

        plugin_id = getattr(plugin, "id", None) or plugin.__class__.__name__
        if not plugin_id:
            plugin_id = str(id(plugin))

        # Check if already loaded
        if plugin_id in self._fibers:
            existing = self._fibers[plugin_id]
            if existing.state == FiberState.ACTIVE:
                return existing

        fiber = Fiber(self.ctx, plugin, config=plugin.config)
        self._fibers[plugin_id] = fiber

        # Check dependency status
        if self._check_dependencies(plugin):
            self._activate_fiber(fiber)
        else:
            fiber.set_state(FiberState.PENDING)
            self._pending_fibers.add(fiber)

        return fiber

    def _check_dependencies(self, plugin: Any) -> bool:
        inject_deps = getattr(plugin, "inject", [])
        if not inject_deps:
            return True
        for dep in inject_deps:
            if not self.ctx.has(dep):
                return False
        return True

    def _activate_fiber(self, fiber: Fiber) -> None:
        fiber.set_state(FiberState.LOADING)
        try:
            fiber.config = resolve_config(fiber.plugin, fiber.config)
            fiber.plugin.ctx = self.ctx
            
            # Setup effect teardown for plugin
            if hasattr(fiber.plugin, "teardown"):
                fiber.effect(fiber.plugin.teardown, label=f"teardown({fiber.name})")

            if fiber in self._pending_fibers:
                self._pending_fibers.remove(fiber)

            fiber.set_state(FiberState.ACTIVE)
            fiber.plugin.apply(self.ctx)
        except Exception as e:
            fiber.set_state(FiberState.FAILED)
            raise e

    def update_dependencies(self) -> None:
        """
        Re-evaluate all PENDING fibers whenever services are added or modified.
        """
        if self._updating:
            return
        self._updating = True
        try:
            pending_list = list(self._pending_fibers)
            for fiber in pending_list:
                if self._check_dependencies(fiber.plugin):
                    self._activate_fiber(fiber)
        finally:
            self._updating = False

    async def unload_plugin(self, plugin_id: str) -> bool:
        """
        Unload and dispose a plugin by id.
        """
        if plugin_id in self._fibers:
            fiber = self._fibers.pop(plugin_id)
            if fiber in self._pending_fibers:
                self._pending_fibers.remove(fiber)
            await fiber.dispose()
            return True
        return False
