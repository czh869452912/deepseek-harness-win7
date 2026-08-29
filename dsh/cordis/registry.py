"""
Plugin registry and dependency injection service
matching reference/vendor/cordis/src/registry.ts
"""

import asyncio
import functools
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dsh.cordis.fiber import Fiber, FiberState, resolve_config


class Inject:
    """
    Utilities for normalizing plugin dependency declarations matching TS Inject namespace.
    """

    @staticmethod
    def resolve(inject_meta: Any, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Convert array/object/class-inherited inject metadata into a plain dict (name -> config).
        Supports:
          - ["tools", "fs?"]  # '?' suffix declares optional dependency
          - {"tools": True, "fs": False}
          - {"tools": {"required": False}}
        """
        if result is None:
            result = {}
        if not inject_meta:
            return result
        if isinstance(inject_meta, (list, tuple, set)):
            for name in inject_meta:
                name_str = str(name)
                if name_str.endswith("?"):
                    result[name_str[:-1]] = {"required": False}
                else:
                    if name_str not in result:
                        result[name_str] = None
        elif isinstance(inject_meta, dict):
            for k, v in inject_meta.items():
                k_str = str(k)
                if isinstance(v, bool):
                    result[k_str] = {"required": v}
                elif isinstance(v, dict):
                    cfg = dict(v)
                    cfg.setdefault("required", True)
                    result[k_str] = cfg
                elif v is None:
                    if k_str.endswith("?"):
                        result[k_str[:-1]] = {"required": False}
                    else:
                        result[k_str] = None
                else:
                    result[k_str] = v
        elif isinstance(inject_meta, str):
            if inject_meta.endswith("?"):
                result[inject_meta[:-1]] = {"required": False}
            else:
                result[inject_meta] = None
        return result


def inject(name_or_deps: Any = None, config: Optional[Any] = None) -> Callable[[Any], Any]:
    """
    Decorator for declaring service dependencies on classes or class methods matching TS @Inject().
    Can be used as:
      @inject("tools")
      @inject(["tools", "fs"])
      @inject({"tools": {"intercept": True}})
      class MyPlugin(Plugin): ...

      @inject("llm")
      def my_method(self): ...
    """
    def decorator(target: Any) -> Any:
        if inspect.isclass(target):
            # Class decorator
            if not hasattr(target, "inject") or not isinstance(getattr(target, "inject"), dict):
                cur_inject = {}
                if hasattr(target, "inject"):
                    raw = getattr(target, "inject")
                    cur_inject = Inject.resolve(raw)
                target.inject = cur_inject

            Inject.resolve(name_or_deps, target.inject)
            if isinstance(name_or_deps, str) and config is not None:
                target.inject[name_or_deps] = config
            return target
        elif callable(target):
            # Method or function decorator
            if not hasattr(target, "_cordis_inject"):
                target._cordis_inject = {}
            Inject.resolve(name_or_deps, target._cordis_inject)
            if isinstance(name_or_deps, str) and config is not None:
                target._cordis_inject[name_or_deps] = config

            @functools.wraps(target)
            def wrapper(self_or_ctx: Any, *args: Any, **kwargs: Any) -> Any:
                ctx = getattr(self_or_ctx, "ctx", None) or (self_or_ctx if hasattr(self_or_ctx, "has") else None)
                if ctx and hasattr(ctx, "has"):
                    for dep in target._cordis_inject.keys():
                        if not ctx.has(dep):
                            raise RuntimeError(f"Cannot call method '{target.__name__}' without injected service '{dep}' in active context")
                return target(self_or_ctx, *args, **kwargs)

            wrapper._cordis_inject = target._cordis_inject
            return wrapper
        return target

    if name_or_deps is not None and (inspect.isclass(name_or_deps) or callable(name_or_deps)):
        # Bare @inject without args
        target_obj = name_or_deps
        name_or_deps = None
        return decorator(target_obj)

    return decorator


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
    dynamic composite epoch dependency injection.
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

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None, get_outer_stack: Optional[Callable[[], List[str]]] = None) -> Fiber:
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
        if inspect.isclass(plugin_cls_or_instance):
            from dsh.cordis.service import Service
            if issubclass(plugin_cls_or_instance, Service):
                try:
                    plugin_inst = plugin_cls_or_instance(self.ctx, config=config)
                except TypeError:
                    try:
                        plugin_inst = plugin_cls_or_instance(self.ctx)
                    except TypeError:
                        plugin_inst = plugin_cls_or_instance()
            elif issubclass(plugin_cls_or_instance, Plugin):
                plugin_inst = plugin_cls_or_instance(config=config)
            else:
                try:
                    plugin_inst = plugin_cls_or_instance(self.ctx, config=config)
                except TypeError:
                    try:
                        plugin_inst = plugin_cls_or_instance(config=config)
                    except TypeError:
                        try:
                            plugin_inst = plugin_cls_or_instance(self.ctx)
                        except TypeError:
                            plugin_inst = plugin_cls_or_instance()
        elif isinstance(plugin_cls_or_instance, Plugin):
            plugin_inst = plugin_cls_or_instance
            if config:
                plugin_inst.config.update(config)
        else:
            plugin_inst = plugin_cls_or_instance

        # Extract declared dependencies via Inject.resolve
        raw_inject = getattr(plugin_cls_or_instance, "inject", None) or getattr(plugin_inst, "inject", None)
        inject_deps = Inject.resolve(raw_inject)

        # Collect method-level @inject hooks matching TS @Inject method decorator
        if plugin_inst is not None:
            init_hooks = getattr(plugin_inst, "_init_hooks", None)
            if init_hooks is None:
                init_hooks = []
                setattr(plugin_inst, "_init_hooks", init_hooks)

            cls = type(plugin_inst)
            for attr_name in dir(plugin_inst):
                if attr_name.startswith("__"):
                    continue
                try:
                    attr = getattr(plugin_inst, attr_name)
                    func = getattr(attr, "__func__", attr)
                    cls_attr = getattr(cls, attr_name, None)
                    cls_func = getattr(cls_attr, "__func__", cls_attr)

                    method_inject = getattr(attr, "_cordis_inject", None) or getattr(func, "_cordis_inject", None) or getattr(cls_attr, "_cordis_inject", None) or getattr(cls_func, "_cordis_inject", None)
                    if callable(attr) and method_inject:
                        hook_reg_key = f"_init_hook_reg_{attr_name}"
                        if getattr(plugin_inst, hook_reg_key, False):
                            continue
                        setattr(plugin_inst, hook_reg_key, True)

                        def _make_hook(m_name=attr_name, m_inj=method_inject):
                            def _hook():
                                target_ctx = getattr(plugin_inst, "ctx", None) or self.ctx
                                if target_ctx and hasattr(target_ctx, "inject"):
                                    def _on_injected(inj_ctx):
                                        old_ctx = getattr(plugin_inst, "ctx", None)
                                        try:
                                            plugin_inst.ctx = inj_ctx
                                            m = getattr(plugin_inst, m_name)
                                            return m()
                                        finally:
                                            if old_ctx is not None:
                                                plugin_inst.ctx = old_ctx
                                    target_ctx.inject(m_inj, _on_injected)
                            return _hook

                        init_hooks.append(_make_hook())
                except Exception:
                    pass

        fiber = Fiber(self.ctx, plugin_inst, config=config, runtime=runtime, inject=inject_deps, get_outer_stack=get_outer_stack)
        try:
            self.ctx.emit("internal/plugin", fiber)
        except Exception as e:
            self._runtimes.pop(callback, None)
            raise e

        runtime.add_fiber(fiber)

        # Evaluate dependencies via composite epoch refresh
        for name in list(fiber.inject.keys()):
            fiber._checkImpl(name)
        fiber._refresh()

        if fiber.state == FiberState.PENDING:
            self._pending_fibers.add(fiber)

        return fiber

    def inject(self, deps: Any, callback: Callable[..., Any]) -> Fiber:
        """
        Start a callback once the requested dependencies are available.
        """
        inject_dict = Inject.resolve(deps)

        class InjectPlugin:
            name = getattr(callback, "__name__", "inject_callback")
            inject = inject_dict

            def apply(self, c: Any) -> Any:
                return callback(c)

        return self.plugin(InjectPlugin())

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
                for name in list(fiber.inject.keys()):
                    fiber._checkImpl(name)
                fiber._refresh()
                if fiber.state == FiberState.ACTIVE and fiber in self._pending_fibers:
                    self._pending_fibers.remove(fiber)
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
