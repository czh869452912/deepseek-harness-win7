"""
Cordis Config Watcher & HMR Service matching reference/vendor/hmr/src/index.ts.
Provides safe configuration and module watching, debouncing, serialized refreshes,
dynamic Python module reload, and 'hmr/change', 'hmr/reload', 'hmr/config-update-failed' events.
"""

import asyncio
import importlib
import importlib.util
import inspect
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class ConfigRefreshState:
    def __init__(self):
        self.dirty: bool = False
        self.running: Optional[asyncio.Task] = None


class ConfigWatcherService(Service):
    """
    Configuration and Python module watching service matching TS Hmr.
    Provides register_config(), register_module(), debouncing, serialized transactional reloads,
    and 'hmr/change', 'hmr/reload', 'hmr/config-update-failed' event broadcasts.
    """

    name = "hmr"

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, name="hmr")
        self.config = config or {}
        self.debounce_ms: float = float(self.config.get("debounce", 100))
        self._configs: Dict[str, Callable[[], Any]] = {}
        self._modules: Dict[str, Optional[Any]] = {}
        self._mtimes: Dict[str, float] = {}
        self._refreshes: Dict[str, ConfigRefreshState] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._running = True

        # Start background polling timer for portable zero-dependency Windows 7 file watching
        try:
            loop = asyncio.get_running_loop()
            self._poll_task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(max(0.1, self.debounce_ms / 1000.0))

                # 1. Check registered config files
                for filename, refresh_fn in list(self._configs.items()):
                    if not os.path.exists(filename):
                        continue
                    try:
                        mtime = os.path.getmtime(filename)
                    except OSError:
                        continue
                    last_mtime = self._mtimes.get(filename, 0.0)
                    if mtime > last_mtime:
                        self._mtimes[filename] = mtime
                        if last_mtime > 0:  # Skip initial check
                            self._trigger_config_refresh(filename, refresh_fn)

                # 2. Check registered module files
                for filename, target_plugin in list(self._modules.items()):
                    if not os.path.exists(filename):
                        continue
                    try:
                        mtime = os.path.getmtime(filename)
                    except OSError:
                        continue
                    last_mtime = self._mtimes.get(filename, 0.0)
                    if mtime > last_mtime:
                        self._mtimes[filename] = mtime
                        if last_mtime > 0:
                            self._trigger_module_reload(filename, target_plugin)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("Exception in poll loop: %s", e)

    def _trigger_config_refresh(self, filename: str, refresh_fn: Callable[[], Any]) -> None:
        state = self._refreshes.setdefault(filename, ConfigRefreshState())
        state.dirty = True
        if state.running and not state.running.done():
            return

        async def _run() -> None:
            while state.dirty:
                state.dirty = False
                try:
                    if hasattr(self.ctx, "emit"):
                        self.ctx.emit("hmr/change", filename)
                    res = refresh_fn()
                    if inspect.isawaitable(res):
                        await res
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded config file %s", filename)
                except Exception as reason:
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").warn("Config reload at %s failed: %s", filename, reason)
                    if hasattr(self.ctx, "parallel"):
                        try:
                            await self.ctx.parallel("hmr/config-update-failed", filename, reason)
                        except Exception:
                            pass

        try:
            loop = asyncio.get_running_loop()
            state.running = loop.create_task(_run())
        except RuntimeError:
            if hasattr(self.ctx, "emit"):
                self.ctx.emit("hmr/change", filename)
            res = refresh_fn()
            if inspect.isawaitable(res):
                try:
                    asyncio.run(res)
                except Exception:
                    pass

    def _trigger_module_reload(self, filename: str, target_plugin: Optional[Any]) -> None:
        state = self._refreshes.setdefault(filename, ConfigRefreshState())
        state.dirty = True
        if state.running and not state.running.done():
            return

        async def _run() -> None:
            while state.dirty:
                state.dirty = False
                reloads: Dict[Any, Dict[str, Any]] = {}
                try:
                    if hasattr(self.ctx, "emit"):
                        self.ctx.emit("hmr/change", filename)

                    # Dynamic reload Python module
                    mod_name = f"hmr_reloaded_{abs(hash(filename))}"
                    spec = importlib.util.spec_from_file_location(mod_name, filename)
                    if not spec or not spec.loader:
                        raise ImportError(f"Cannot load module spec from {filename}")
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    spec.loader.exec_module(mod)

                    registry = getattr(self.ctx, "registry", None)
                    if not registry:
                        return

                    # Find all plugin classes in module
                    found_classes: List[Tuple[Any, Any]] = []
                    if target_plugin and isinstance(target_plugin, type):
                        new_cls = getattr(mod, target_plugin.__name__, None)
                        if new_cls:
                            found_classes.append((target_plugin, new_cls))
                    else:
                        for attr_name in dir(mod):
                            obj = getattr(mod, attr_name)
                            if isinstance(obj, type) and (issubclass(obj, Plugin) or hasattr(obj, "apply")):
                                for reg_key in list(registry._runtimes.keys()):
                                    if getattr(reg_key, "__name__", "") == attr_name:
                                        found_classes.append((reg_key, obj))

                    for old_key, new_cls in found_classes:
                        runtime = registry.get(old_key)
                        if runtime:
                            # Update registry key
                            runtime.callback = new_cls
                            registry._runtimes.pop(old_key, None)
                            registry._runtimes[new_cls] = runtime

                            # Restart fibers with new plugin class
                            for fiber in list(runtime.fibers):
                                if isinstance(fiber.plugin, Plugin):
                                    new_inst = new_cls(config=fiber.config)
                                    new_inst.id = getattr(fiber.plugin, "id", None)
                                    new_inst.ctx = fiber.ctx
                                    fiber.plugin = new_inst
                                else:
                                    fiber.plugin = new_cls
                                await fiber.restart()

                            reloads[old_key] = {"filename": filename, "runtime": runtime}

                    if reloads and hasattr(self.ctx, "emit"):
                        self.ctx.emit("hmr/reload", reloads)

                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded module %s (%d plugins)", filename, len(reloads))

                except Exception as reason:
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").warn("Module reload at %s failed: %s", filename, reason)
                    if hasattr(self.ctx, "parallel"):
                        try:
                            await self.ctx.parallel("hmr/config-update-failed", filename, reason)
                        except Exception:
                            pass

        try:
            loop = asyncio.get_running_loop()
            state.running = loop.create_task(_run())
        except RuntimeError:
            pass

    def register_config(self, filename: str, refresh_fn: Callable[[], Any]) -> Callable[[], None]:
        """
        Watch one exact config path and execute refresh_fn on modification matching TS hmr.registerConfig.
        """
        abs_path = os.path.abspath(filename)
        if os.path.exists(abs_path):
            self._mtimes[abs_path] = os.path.getmtime(abs_path)
        else:
            self._mtimes[abs_path] = time.time()

        self._configs[abs_path] = refresh_fn

        def unregister() -> None:
            self._configs.pop(abs_path, None)
            self._mtimes.pop(abs_path, None)
            self._refreshes.pop(abs_path, None)

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(unregister, label=f"hmr.register_config('{abs_path}')")
        return unregister

    def register_module(self, filename: str, plugin_cls: Optional[Any] = None) -> Callable[[], None]:
        """
        Watch a Python module file and dynamically reload its plugins on modification matching TS Hmr module watch.
        """
        abs_path = os.path.abspath(filename)
        if os.path.exists(abs_path):
            self._mtimes[abs_path] = os.path.getmtime(abs_path)
        else:
            self._mtimes[abs_path] = time.time()

        self._modules[abs_path] = plugin_cls

        def unregister() -> None:
            self._modules.pop(abs_path, None)
            self._mtimes.pop(abs_path, None)
            self._refreshes.pop(abs_path, None)

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(unregister, label=f"hmr.register_module('{abs_path}')")
        return unregister

    def teardown(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._configs.clear()
        self._modules.clear()
        self._mtimes.clear()


# Backward-compatible and alias names
Hmr = ConfigWatcherService
HmrService = ConfigWatcherService
