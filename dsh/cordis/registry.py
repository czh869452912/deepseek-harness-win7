"""
Plugin registry and dependency injection service
matching reference/vendor/cordis/src/registry.ts
"""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
from dsh.cordis.fiber import Fiber, FiberState


class Inject:
    """Normalize Cordis array/map dependency declarations to a plain map."""

    @staticmethod
    def resolve(deps: Any, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resolved = result if result is not None else {}
        if not deps:
            return resolved
        if isinstance(deps, (list, tuple)):
            for name in deps:
                resolved[name] = None
        elif isinstance(deps, dict):
            for name, config in deps.items():
                resolved[name] = config if config is not None else None
        else:
            resolved[deps] = None
        return resolved


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
        self._dependency_updates: List[Tuple[Optional[List[str]], Any]] = []

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

    def keys(self) -> Iterator[Any]:
        return iter(self._runtimes.keys())

    def values(self) -> Iterator[PluginRuntime]:
        return iter(self._runtimes.values())

    def entries(self) -> Iterator[Tuple[Any, PluginRuntime]]:
        return iter(self._runtimes.items())

    def for_each(self, callback: Callable[[PluginRuntime, Any], Any]) -> None:
        for key, value in self._runtimes.items():
            callback(value, key)

    def list_fibers(self) -> List[Fiber]:
        fibers: List[Fiber] = []
        for runtime in self._runtimes.values():
            fibers.extend(runtime.fibers)
        for f in self._pending_fibers:
            if f not in fibers:
                fibers.append(f)
        return fibers

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None, parent_ctx: Any = None) -> Fiber:
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

        owner_ctx = parent_ctx or self.ctx
        owner_ctx.fiber.assert_active()

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

        inject_map = Inject.resolve(getattr(plugin_inst, "inject", None))
        fiber = Fiber(owner_ctx, plugin_inst, config=config, runtime=runtime)
        fiber.inject = inject_map
        if inject_map:
            fiber.ctx._intercept_map = dict(owner_ctx._intercept_map)
            for dep_name, intercept_config in inject_map.items():
                if intercept_config is not None:
                    fiber.ctx._intercept_map[dep_name] = intercept_config
                    fiber.ctx._own_intercepts[dep_name] = intercept_config

        def own_child() -> Callable[[], Any]:
            runtime.add_fiber(fiber)

            async def dispose_child() -> None:
                await fiber.dispose()
                if not runtime.fibers and self._runtimes.get(callback) is runtime:
                    self._runtimes.pop(callback, None)

            return dispose_child

        owner_ctx.fiber.effect(own_child, label="ctx.plugin()")

        teardown = getattr(plugin_inst, "teardown", None)
        if callable(teardown):
            fiber.effect(lambda: teardown, label="teardown(%s)" % fiber.name)

        try:
            fiber.ctx.emit("internal/plugin", fiber)
        except Exception:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(fiber.dispose())
            else:
                loop.create_task(fiber.dispose())
            raise

        if fiber.uid is not None and owner_ctx.fiber.state != FiberState.UNLOADING:
            self._pending_fibers.add(fiber)
            self.refresh_fiber(fiber)

        return fiber

    def inject(self, deps: Any, callback: Callable[..., Any], parent_ctx: Any = None) -> Fiber:
        """
        Start a callback once the requested dependencies are available.
        """
        inject_map = Inject.resolve(deps)

        class InjectPlugin:
            name = getattr(callback, "__name__", "inject_callback")
            inject = inject_map

            def apply(self, c: Any) -> Any:
                return callback(c)

        return self.plugin(InjectPlugin(), parent_ctx=parent_ctx)

    def _check_dependencies(self, plugin: Any) -> bool:
        inject_deps = Inject.resolve(getattr(plugin, "inject", None))
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

    def refresh_fiber(self, fiber: Fiber) -> bool:
        from dsh.cordis.fiber import INACTIVE_EPOCH
        from dsh.cordis.utils import get_traceable

        epoch = ""
        fiber._store = {}
        for name in getattr(fiber, "inject", {}):
            impl = self.ctx.reflect._get_impl(fiber.ctx, name, strict=True)
            if impl is None:
                epoch = INACTIVE_EPOCH
                break
            if impl.check:
                try:
                    service = get_traceable(fiber.ctx, impl.value)
                    try:
                        parameters = inspect.signature(impl.check).parameters.values()
                        accepts_receiver = any(
                            parameter.kind in (
                                inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                inspect.Parameter.VAR_POSITIONAL,
                            )
                            for parameter in parameters
                        )
                    except (TypeError, ValueError):
                        accepts_receiver = False
                    available = impl.check(service) if accepts_receiver else impl.check()
                    if not available:
                        epoch = INACTIVE_EPOCH
                        break
                except Exception as error:
                    impl.fiber._log_error(error)
                    epoch = INACTIVE_EPOCH
                    break
            fiber._store[name] = impl
            epoch += ":%s" % impl.fiber.uid

        old_epoch = fiber.epoch
        if epoch == INACTIVE_EPOCH:
            self._pending_fibers.add(fiber)
            fiber.set_epoch(epoch)
            return old_epoch != fiber.epoch

        self._pending_fibers.discard(fiber)
        if hasattr(fiber.plugin, "ctx"):
            fiber.plugin.ctx = fiber.ctx
        self._start_fiber(fiber, epoch)
        return old_epoch != fiber.epoch

    def _start_fiber(self, fiber: Fiber, epoch: str) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            async def activate() -> None:
                fiber.set_epoch(epoch)
                await fiber

            asyncio.run(activate())
        else:
            fiber.set_epoch(epoch)

    def update_dependencies(
        self,
        names: Optional[List[str]] = None,
        source_ctx: Any = None,
    ) -> List[Fiber]:
        """
        Re-evaluate all PENDING fibers whenever services are added or modified.
        """
        queued_names = list(names) if names is not None else None
        self._dependency_updates.append((queued_names, source_ctx))
        if self._updating:
            return []
        self._updating = True
        affected: List[Fiber] = []
        try:
            while self._dependency_updates:
                current_names, current_source_ctx = self._dependency_updates.pop(0)
                for fiber in list(self.list_fibers()):
                    if getattr(fiber, "uid", None) is None:
                        continue
                    if current_names is not None:
                        dependencies = getattr(fiber, "inject", {})
                        matching = False
                        for name in current_names:
                            if name not in dependencies:
                                continue
                            source_key = getattr(
                                current_source_ctx, "_isolated_keys", {}
                            ).get(name, name)
                            fiber_key = getattr(
                                fiber.ctx, "_isolated_keys", {}
                            ).get(name, name)
                            if source_key == fiber_key:
                                matching = True
                                break
                        if not matching:
                            continue
                    if self.refresh_fiber(fiber) and fiber not in affected:
                        affected.append(fiber)
        finally:
            self._updating = False
        return affected

    async def unload_plugin(self, plugin_id: str) -> bool:
        """
        Unload and dispose a plugin by id or callback name.
        """
        for runtime in list(self._runtimes.values()):
            for fiber in list(runtime.fibers):
                if fiber.name == plugin_id or getattr(fiber.plugin, "id", None) == plugin_id:
                    if fiber in self._pending_fibers:
                        self._pending_fibers.remove(fiber)
                    await fiber.dispose()
                    if not runtime.fibers:
                        self._runtimes.pop(runtime.callback, None)
                    return True
        return False
