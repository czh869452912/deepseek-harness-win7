"""
Plugin registry and dependency injection service
matching reference/vendor/cordis/src/registry.ts
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dsh.cordis.fiber import Fiber, FiberState, resolve_config


class PluginRuntime:
    """
    Mutable registry record shared by all fibers of one plugin callback.
    """

    def __init__(self, callback: Any, name: Optional[str] = None):
        self.callback = callback
        self.name = name or getattr(callback, "name", None) or getattr(callback, "__name__", "anonymous")
        self.fibers: List[Fiber] = []

    def add_fiber(self, fiber: Fiber) -> None:
        if fiber not in self.fibers:
            self.fibers.append(fiber)

    def remove_fiber(self, fiber: Fiber) -> None:
        if fiber in self.fibers:
            self.fibers.remove(fiber)

    def __repr__(self) -> str:
        return f"<PluginRuntime {self.name} fibers={len(self.fibers)}>"


class RegistryService:
    """
    Plugin registry service for Cordis.
    Normalizes plugin shapes, tracks plugin runtimes, starts fibers, and manages
    dynamic dependency injection.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._counter = 0
        self._runtimes: Dict[Any, PluginRuntime] = {}
        self._pending_fibers: Set[Fiber] = set()
        self._updating = False

    @property
    def counter(self) -> int:
        self._counter += 1
        return self._counter

    @property
    def size(self) -> int:
        return len(self._runtimes)

    def resolve(self, plugin: Any) -> Optional[Any]:
        """
        Resolve a supported plugin shape to its executable callback/class identity.
        """
        if not plugin:
            return None
        if callable(plugin):
            return plugin
        if hasattr(plugin, "apply") and callable(plugin.apply):
            return plugin.apply
        return None

    def get(self, plugin: Any) -> Optional[PluginRuntime]:
        key = self.resolve(plugin)
        return self._runtimes.get(key) if key else None

    def get_fiber(self, plugin_id_or_name: str) -> Optional[Fiber]:
        for fiber in self.list_fibers():
            if fiber.name == plugin_id_or_name or getattr(fiber.plugin, "id", None) == plugin_id_or_name:
                return fiber
        return None

    def has(self, plugin: Any) -> bool:
        key = self.resolve(plugin)
        return bool(key and key in self._runtimes)

    def delete(self, plugin: Any) -> Optional[PluginRuntime]:
        """
        Dispose every running fiber for a plugin and remove its runtime record.
        """
        key = self.resolve(plugin)
        runtime = self._runtimes.pop(key, None) if key else None
        if runtime:
            for fiber in list(runtime.fibers):
                if fiber in self._pending_fibers:
                    self._pending_fibers.remove(fiber)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(fiber.dispose())
                except RuntimeError:
                    asyncio.run(fiber.dispose())
        return runtime

    def list_fibers(self) -> List[Fiber]:
        fibers: List[Fiber] = []
        for runtime in self._runtimes.values():
            fibers.extend(runtime.fibers)
        for f in self._pending_fibers:
            if f not in fibers:
                fibers.append(f)
        return fibers

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None) -> Fiber:
        """
        Start a plugin in the current context and return its fiber.
        Supports Functions, Classes, and Object plugins with apply().
        """
        from dsh.cordis.plugin import Plugin

        callback = self.resolve(plugin_cls_or_instance)
        if not callback and isinstance(plugin_cls_or_instance, Plugin):
            callback = plugin_cls_or_instance.apply

        if not callback and inspect.isclass(plugin_cls_or_instance):
            callback = plugin_cls_or_instance

        if not callback:
            raise ValueError(f"Invalid plugin, expected function, class, or object with 'apply' method: {plugin_cls_or_instance}")

        self.ctx.fiber.assert_active()

        runtime = self._runtimes.get(callback)
        if not runtime:
            name = getattr(plugin_cls_or_instance, "name", None) or getattr(plugin_cls_or_instance, "id", None)
            runtime = PluginRuntime(callback=callback, name=name)
            self._runtimes[callback] = runtime

        # Plugin instantiation
        if isinstance(plugin_cls_or_instance, Plugin):
            plugin_inst = plugin_cls_or_instance
            if config:
                plugin_inst.config.update(config)
        elif inspect.isclass(plugin_cls_or_instance) and issubclass(plugin_cls_or_instance, Plugin):
            plugin_inst = plugin_cls_or_instance(config=config)
        else:
            plugin_inst = plugin_cls_or_instance

        fiber = Fiber(self.ctx, plugin_inst, config=config, runtime=runtime)
        runtime.add_fiber(fiber)

        if self._check_dependencies(plugin_inst):
            self._activate_fiber(fiber)
        else:
            fiber.set_state(FiberState.PENDING)
            self._pending_fibers.add(fiber)

        return fiber

    def inject(self, deps: Any, callback: Callable[..., Any]) -> Fiber:
        """
        Start a callback once the requested dependencies are available.
        """
        inject_list = deps if isinstance(deps, (list, tuple)) else list(deps.keys()) if isinstance(deps, dict) else [deps]

        class InjectPlugin:
            name = getattr(callback, "__name__", "inject_callback")
            inject = inject_list

            def apply(self, c: Any) -> Any:
                return callback(c)

        return self.plugin(InjectPlugin())

    def _check_dependencies(self, plugin: Any) -> bool:
        inject_deps = getattr(plugin, "inject", [])
        if not inject_deps:
            return True
        if isinstance(inject_deps, (list, tuple)):
            for dep in inject_deps:
                if not self.ctx.has(dep):
                    return False
        elif isinstance(inject_deps, dict):
            for dep in inject_deps.keys():
                if not self.ctx.has(dep):
                    return False
        return True

    def _activate_fiber(self, fiber: Fiber) -> None:
        fiber.set_state(FiberState.ACTIVE)
        try:
            fiber.config = resolve_config(fiber.plugin, fiber._config)
            if hasattr(fiber.plugin, "ctx"):
                fiber.plugin.ctx = fiber.ctx

            if hasattr(fiber.plugin, "teardown") and callable(fiber.plugin.teardown):
                fiber.effect(fiber.plugin.teardown, label=f"teardown({fiber.name})")

            if fiber in self._pending_fibers:
                self._pending_fibers.remove(fiber)

            fiber.set_epoch("active_epoch")
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
        Unload and dispose a plugin by id or callback name.
        """
        for runtime in list(self._runtimes.values()):
            for fiber in list(runtime.fibers):
                if fiber.name == plugin_id or getattr(fiber.plugin, "id", None) == plugin_id:
                    runtime.remove_fiber(fiber)
                    if fiber in self._pending_fibers:
                        self._pending_fibers.remove(fiber)
                    await fiber.dispose()
                    if not runtime.fibers:
                        self._runtimes.pop(runtime.callback, None)
                    return True
        return False
