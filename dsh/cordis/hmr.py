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
import ast
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class ModuleDependencyGraph:
    """
    Lightweight AST-based module dependency analyzer for transitive HMR reloads.
    Tracks which local Python files import which other files without executing code.
    Compatible with Python 3.8.10 and Windows 7 SP1.
    """

    def __init__(self):
        # file_path -> Set[imported_file_path]
        self.dependencies: Dict[str, Set[str]] = {}
        # file_path -> Set[dependent_file_path] (reverse graph)
        self.dependents: Dict[str, Set[str]] = {}

    def scan_file(self, filepath: str, base_dir: Optional[str] = None) -> Set[str]:
        abs_path = os.path.abspath(filepath)
        if not os.path.isfile(abs_path):
            return set()
        cur_dir = os.path.dirname(abs_path)
        base = base_dir or cur_dir

        imported_files: Set[str] = set()
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source, filename=abs_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod_file = self._resolve_module(alias.name, cur_dir, base)
                        if mod_file:
                            imported_files.add(mod_file)
                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    if getattr(node, "level", 0) > 0:
                        target_dir = cur_dir
                        for _ in range(node.level - 1):
                            target_dir = os.path.dirname(target_dir)
                        mod_file = self._resolve_relative(mod_name, target_dir)
                        if mod_file:
                            imported_files.add(mod_file)
                    else:
                        mod_file = self._resolve_module(mod_name, cur_dir, base)
                        if mod_file:
                            imported_files.add(mod_file)
        except Exception:
            pass

        # Update forward & reverse graphs
        old_imports = self.dependencies.get(abs_path, set())
        for old_f in old_imports:
            if old_f in self.dependents:
                self.dependents[old_f].discard(abs_path)

        self.dependencies[abs_path] = imported_files
        for new_f in imported_files:
            self.dependents.setdefault(new_f, set()).add(abs_path)
        return imported_files

    def _resolve_relative(self, mod_name: str, target_dir: str) -> Optional[str]:
        if not mod_name:
            init_py = os.path.join(target_dir, "__init__.py")
            if os.path.isfile(init_py):
                return os.path.abspath(init_py)
            return None
        parts = mod_name.split(".")
        cand_file = os.path.join(target_dir, *parts) + ".py"
        if os.path.isfile(cand_file):
            return os.path.abspath(cand_file)
        cand_dir_init = os.path.join(target_dir, *parts, "__init__.py")
        if os.path.isfile(cand_dir_init):
            return os.path.abspath(cand_dir_init)
        return None

    def _resolve_module(self, mod_name: str, cur_dir: str, base_dir: str) -> Optional[str]:
        if not mod_name:
            return None
        parts = mod_name.split(".")
        for b in (cur_dir, base_dir, os.getcwd()):
            cand = os.path.join(b, *parts) + ".py"
            if os.path.isfile(cand):
                return os.path.abspath(cand)
            cand_init = os.path.join(b, *parts, "__init__.py")
            if os.path.isfile(cand_init):
                return os.path.abspath(cand_init)
        return None

    def get_transitive_dependents(self, changed_file: str) -> List[str]:
        """Return topological list of all files that depend on changed_file."""
        abs_path = os.path.abspath(changed_file)
        visited: Set[str] = set()
        order: List[str] = []

        def dfs(node: str):
            if node in visited:
                return
            visited.add(node)
            for dep in self.dependents.get(node, set()):
                dfs(dep)
            order.append(node)

        for dep in self.dependents.get(abs_path, set()):
            dfs(dep)
        return order


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
        self.graph = ModuleDependencyGraph()
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
                abs_changed = os.path.abspath(filename)
                try:
                    if hasattr(self.ctx, "emit"):
                        self.ctx.emit("hmr/change", abs_changed)

                    # 1. Update AST dependency graph
                    self.graph.scan_file(abs_changed)

                    # 2. Determine all files to reload: changed file + transitive dependents
                    dependents = self.graph.get_transitive_dependents(abs_changed)
                    files_to_reload = [abs_changed] + [f for f in dependents if f != abs_changed]

                    registry = getattr(self.ctx, "registry", None)

                    for file_path in files_to_reload:
                        if not os.path.isfile(file_path):
                            continue

                        # Dynamic reload Python module
                        mod_name = f"hmr_reloaded_{abs(hash(file_path))}"
                        spec = importlib.util.spec_from_file_location(mod_name, file_path)
                        if not spec or not spec.loader:
                            continue
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = mod
                        spec.loader.exec_module(mod)

                        if not registry:
                            continue

                        # Find all plugin classes in module
                        found_classes: List[Tuple[Any, Any]] = []
                        tgt = target_plugin if file_path == abs_changed else self._modules.get(file_path)
                        if tgt and isinstance(tgt, type):
                            new_cls = getattr(mod, tgt.__name__, None)
                            if new_cls:
                                found_classes.append((tgt, new_cls))
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
                                runtime.callback = new_cls
                                registry._runtimes.pop(old_key, None)
                                registry._runtimes[new_cls] = runtime

                                for fiber in list(runtime.fibers):
                                    if isinstance(fiber.plugin, Plugin):
                                        new_inst = new_cls(config=fiber.config)
                                        new_inst.id = getattr(fiber.plugin, "id", None)
                                        new_inst.ctx = fiber.ctx
                                        fiber.plugin = new_inst
                                    else:
                                        fiber.plugin = new_cls
                                    await fiber.restart()

                                reloads[old_key] = {"filename": file_path, "runtime": runtime}

                    if reloads and hasattr(self.ctx, "emit"):
                        self.ctx.emit("hmr/reload", reloads)

                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded module %s (%d plugins affected)", filename, len(reloads))

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
        self.graph.scan_file(abs_path)

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
