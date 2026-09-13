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
from dsh.cordis.utils import SharedCounter


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
          - {"tools": {"intercept": True}}
        """
        if result is None:
            result = {}
        if not inject_meta:
            return result
        if isinstance(inject_meta, (list, tuple, set)):
            for name in inject_meta:
                name_str = str(name)
                result[name_str] = None
        elif isinstance(inject_meta, dict):
            for k, v in inject_meta.items():
                k_str = str(k)
                result[k_str] = None if v is None else v
        elif isinstance(inject_meta, str):
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
            # Own attribute check matching TS Object.hasOwn(value, 'inject')
            if "inject" not in target.__dict__:
                base_inject = getattr(target, "inject", {})
                target.inject = dict(Inject.resolve(base_inject))
            elif not isinstance(target.inject, dict):
                target.inject = dict(Inject.resolve(target.inject))

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
                ctx = getattr(self_or_ctx, "ctx", self_or_ctx)
                if ctx and hasattr(ctx, "has") and hasattr(ctx, "inject"):
                    missing = [dep for dep in target._cordis_inject.keys() if not ctx.has(dep)]
                    if missing:
                        def _on_ready(injected_ctx: Any) -> Any:
                            return target(self_or_ctx, *args, **kwargs)
                        return ctx.inject(missing, _on_ready)
                return target(self_or_ctx, *args, **kwargs)

            wrapper._cordis_inject = target._cordis_inject
            return wrapper
        else:
            raise TypeError("@Inject() can only be used on class or class methods")

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

    def __init__(self, callback: Any, name: Optional[str] = None, Config: Any = None):
        self.callback = callback
        cb_name = getattr(callback, "name", None) or getattr(callback, "__name__", None)
        if cb_name and (cb_name in ("<lambda>", "anonymous", "apply") or cb_name.startswith("anonymous")):
            cb_name = None
        self.name = name or cb_name
        self.Config = Config
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
        # `registry.ts` installs one RegistryService per application and every
        # derived context resolves `ctx.registry` to that same instance through
        # the context prototype chain, so `counter` allocates from one sequence
        # for the whole tree. The port binds a per-context view (a shallow copy),
        # so the allocator lives in a shared cell.
        self._counter = SharedCounter()
        self._runtimes: Dict[Any, PluginRuntime] = {}
        self._pending_fibers: Set[Fiber] = set()
        self._updating = False

    def _bind(self, ctx: Any) -> "RegistryService":
        import copy
        bound = copy.copy(self)
        bound.ctx = ctx
        return bound

    @property
    def counter(self) -> int:
        # `registry.ts` allocates on every read of the single shared counter.
        return self._counter.next()

    @property
    def size(self) -> int:
        return len(self._runtimes)

    def resolve(self, plugin: Any) -> Optional[Any]:
        """
        Resolve a supported plugin shape to its executable callback/class identity.
        """
        if not plugin:
            return None
        try:
            if inspect.isclass(plugin) or inspect.isfunction(plugin) or inspect.isbuiltin(plugin):
                return plugin
            if hasattr(plugin, "apply") and callable(getattr(plugin, "apply", None)):
                return plugin.apply
            if isinstance(plugin, dict) and callable(plugin.get("apply")):
                return plugin["apply"]
            if callable(plugin):
                return plugin
        except Exception:
            return None
        return None

    def get(self, plugin: Any) -> Optional[PluginRuntime]:
        key = self.resolve(plugin)
        return self._runtimes.get(key) if key else None

    def get_fiber(self, plugin_id_or_name: str) -> Optional[Fiber]:
        for fiber in self.list_fibers():
            if (
                fiber.name == plugin_id_or_name
                or getattr(fiber.plugin, "id", None) == plugin_id_or_name
                or getattr(getattr(fiber, "_plugin_cls", None), "id", None) == plugin_id_or_name
            ):
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
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(fiber.dispose())
                        loop.close()
                    except Exception:
                        pass
        return runtime

    async def delete_async(self, plugin: Any) -> Optional[PluginRuntime]:
        key = self.resolve(plugin)
        runtime = self._runtimes.pop(key, None) if key else None
        if runtime:
            for fiber in list(runtime.fibers):
                if fiber in self._pending_fibers:
                    self._pending_fibers.remove(fiber)
                await fiber.dispose()
        return runtime

    def keys(self) -> Any:
        return self._runtimes.keys()

    def values(self) -> Any:
        return self._runtimes.values()

    def entries(self) -> Any:
        return self._runtimes.items()

    def forEach(self, callback: Callable[[PluginRuntime, Any, Any], None]) -> None:
        for k, v in list(self._runtimes.items()):
            callback(v, k, self)

    def list_fibers(self) -> List[Fiber]:
        fibers: List[Fiber] = []
        for runtime in self._runtimes.values():
            fibers.extend(runtime.fibers)
        for f in self._pending_fibers:
            if f not in fibers:
                fibers.append(f)
        return fibers

    def plugin(self, plugin_cls_or_instance: Any, config: Optional[Dict[str, Any]] = None, get_outer_stack: Optional[Callable[[], List[str]]] = None, parent_ctx: Optional[Any] = None) -> Fiber:
        """
        Start a plugin in the current context and return its fiber.
        Supports Functions, Classes, and Object plugins with apply().
        """
        from dsh.cordis.plugin import Plugin

        target_parent = parent_ctx or getattr(self, "ctx", None)

        callback = self.resolve(plugin_cls_or_instance)
        if not callback and isinstance(plugin_cls_or_instance, Plugin):
            callback = plugin_cls_or_instance.apply

        if not callback and inspect.isclass(plugin_cls_or_instance):
            callback = plugin_cls_or_instance

        if not callback:
            p = plugin_cls_or_instance
            if p is None:
                type_str = "undefined"
            elif isinstance(p, bool):
                type_str = "boolean"
            elif isinstance(p, (int, float)):
                type_str = "number"
            elif isinstance(p, str):
                type_str = "string"
            elif callable(p):
                type_str = "function"
            else:
                type_str = "object"
            py_type = type(p).__name__
            raise ValueError(f'invalid plugin, expect function or object with an "apply" method, received {type_str} ({py_type})')

        if target_parent and getattr(target_parent, "fiber", None):
            target_parent.fiber.assert_active()
        elif self.ctx and getattr(self.ctx, "fiber", None):
            self.ctx.fiber.assert_active()

        runtime = self._runtimes.get(callback)
        if not runtime:
            name = getattr(plugin_cls_or_instance, "name", None)
            if not name and isinstance(plugin_cls_or_instance, dict):
                name = plugin_cls_or_instance.get("name")
            if name == "apply":
                name = None
            cfg_schema = getattr(plugin_cls_or_instance, "Config", None)
            if isinstance(plugin_cls_or_instance, dict):
                cfg_schema = cfg_schema or plugin_cls_or_instance.get("Config")
            runtime = PluginRuntime(callback=callback, name=name, Config=cfg_schema)
            self._runtimes[callback] = runtime

        # Extract declared dependencies via Inject.resolve
        if isinstance(plugin_cls_or_instance, dict):
            raw_inject = plugin_cls_or_instance.get("inject")
        else:
            raw_inject = getattr(plugin_cls_or_instance, "inject", None)
        inject_deps = Inject.resolve(raw_inject)

        fiber_config = config
        if fiber_config is None and not inspect.isclass(plugin_cls_or_instance) and hasattr(plugin_cls_or_instance, "config"):
            inst_cfg = getattr(plugin_cls_or_instance, "config", None)
            if inst_cfg is not None:
                fiber_config = inst_cfg

        fiber = Fiber(target_parent, None, config=fiber_config, runtime=runtime, inject=inject_deps, get_outer_stack=get_outer_stack)
        target_ctx = fiber.ctx

        # Plugin instantiation deferred to fiber._reload for class plugins
        if inspect.isclass(plugin_cls_or_instance):
            fiber._plugin_cls = plugin_cls_or_instance
            plugin_inst = None
            if hasattr(plugin_cls_or_instance, "inject") and not raw_inject:
                fiber.inject = Inject.resolve(getattr(plugin_cls_or_instance, "inject", None))
        elif isinstance(plugin_cls_or_instance, Plugin):
            plugin_inst = plugin_cls_or_instance
            fiber.plugin = plugin_inst
            if hasattr(plugin_inst, "inject") and not raw_inject:
                fiber.inject = Inject.resolve(getattr(plugin_inst, "inject", None))
        else:
            plugin_inst = plugin_cls_or_instance
            fiber.plugin = plugin_inst
            if hasattr(plugin_inst, "inject") and not raw_inject:
                fiber.inject = Inject.resolve(getattr(plugin_inst, "inject", None))

        # Collect method-level @inject hooks matching TS @Inject method decorator
        if plugin_inst is not None and not isinstance(plugin_inst, (dict, list, tuple)):
            init_hooks = getattr(plugin_inst, "_init_hooks", None)
            if init_hooks is None:
                init_hooks = []
                try:
                    setattr(plugin_inst, "_init_hooks", init_hooks)
                except (AttributeError, TypeError):
                    pass

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
        runtime.add_fiber(fiber)

        # fiber.ts resolves dependencies only after publication: an
        # `internal/plugin` observer may dispose the fiber (then its teardown owns
        # any collected effects) or add injections, and a reentrant parent unload
        # leaves the unpublished child to the parent's disposal.
        parent_fiber = getattr(target_parent, "fiber", None) if target_parent else None
        if fiber.uid is not None and (parent_fiber is None or parent_fiber.state != FiberState.UNLOADING):
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

            def apply(self, c: Any, config: Any = None) -> Any:
                take_two = False
                try:
                    sig = inspect.signature(callback)
                    params = [p for p in sig.parameters.values() if p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
                    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
                    if len(params) >= 2 or has_varargs:
                        take_two = True
                except (ValueError, TypeError):
                    take_two = False
                if take_two:
                    return callback(c, config)
                return callback(c)

        return self.plugin(InjectPlugin())

    def update_dependencies(self) -> None:
        """
        Re-evaluate dependencies via reflect.notify to maintain single notification channel.
        """
        if hasattr(self.ctx, "reflect") and hasattr(self.ctx.reflect, "notify"):
            names = set()
            for fiber in list(self._pending_fibers):
                names.update(fiber.inject.keys())
            if names:
                self.ctx.reflect.notify(list(names))

    async def unload_plugin(self, target: Any) -> bool:
        """
        Unload and dispose a plugin by plugin object, callback, or name matching TS registry.delete.
        """
        callback = self.resolve(target) if target is not None else None
        if callback is not None and callback in self._runtimes:
            runtime = await self.delete_async(callback)
            return runtime is not None

        for runtime in list(self._runtimes.values()):
            if runtime.name == target or runtime.callback == target:
                res = await self.delete_async(runtime.callback)
                return res is not None
            for fiber in list(runtime.fibers):
                if target in (fiber.name, getattr(fiber.plugin, "id", None), getattr(fiber.plugin, "name", None)):
                    res = await self.delete_async(runtime.callback)
                    return res is not None
        return False
