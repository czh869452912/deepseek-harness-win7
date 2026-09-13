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
import types
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

    def add_dependency(self, file_path: str, dependency_file: str) -> None:
        abs_file = os.path.abspath(file_path)
        abs_dep = os.path.abspath(dependency_file)
        self.dependencies.setdefault(abs_file, set()).add(abs_dep)
        self.dependents.setdefault(abs_dep, set()).add(abs_file)

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


def find_watch_root(filename: str) -> Tuple[str, str, int]:
    filename = os.path.abspath(filename)
    root = os.path.dirname(filename)
    depth = 0
    while True:
        try:
            st = os.stat(root)
            import stat as stat_mod
            if not stat_mod.S_ISDIR(st.st_mode):
                raise RuntimeError(f"config watch parent is not a directory: {root}")
            canonical_root = os.path.realpath(root)
            rel = os.path.relpath(filename, root)
            canonical_filename = os.path.abspath(os.path.join(canonical_root, rel))
            return canonical_filename, canonical_root, depth
        except (FileNotFoundError, OSError):
            parent = os.path.dirname(root)
            if parent == root:
                raise
            root = parent
            depth += 1


class ConfigWatcherService(Service):
    """
    Configuration and Python module watching service matching TS Hmr.
    Provides register_config(), register_module(), debouncing, serialized transactional reloads,
    and 'hmr/change', 'hmr/reload', 'hmr/config-update-failed' event broadcasts.
    """

    name = "hmr"
    inject = ["loader", "timer"]

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, name="hmr")
        self.config = config or {}

        # D8: Verify loader and internal
        loader = self.ctx.get("loader")
        if loader is not None and not getattr(loader, "internal", None):
            raise RuntimeError("--expose-internals is required for HMR service")

        self.debounce_ms: float = float(self.config.get("debounce", 100))
        self._configs: Dict[str, Callable[[], Any]] = {}
        # Canonical registration key -> absolute path observed by HMR, matching the TS
        # `filename` passed to refreshConfig (resolve(baseDir, filename)).
        self._config_names: Dict[str, str] = {}
        self._modules: Dict[str, Optional[Any]] = {}
        self._mtimes: Dict[str, float] = {}
        self._config_contents: Dict[str, bytes] = {}
        self._refreshes: Dict[str, ConfigRefreshState] = {}
        # One serialized module-reload pass plus its pending changed files, so a
        # change detected mid-pass joins that pass instead of racing it.
        self._module_reload_task: Optional[asyncio.Task] = None
        self._module_changes: Dict[str, Any] = {}
        self._refresh_tasks: Set[asyncio.Task] = set()
        self.graph = ModuleDependencyGraph()
        self._poll_task: Optional[asyncio.Task] = None
        self._running = True

        self.base_dir = self.config.get("base")
        if not self.base_dir:
            base_url = getattr(ctx, "baseUrl", None) or getattr(ctx, "base_url", None)
            if not base_url and hasattr(ctx, "root") and ctx.root:
                base_url = getattr(ctx.root, "baseUrl", None) or getattr(ctx.root, "base_url", None)
            if not base_url and hasattr(ctx, "_parent") and ctx._parent:
                base_url = getattr(ctx._parent, "baseUrl", None) or getattr(ctx._parent, "base_url", None)
            if base_url:
                if base_url.startswith("file://"):
                    import urllib.parse
                    parsed = urllib.parse.urlparse(base_url)
                    p = urllib.parse.unquote(parsed.path)
                    if sys.platform == "win32" and p.startswith("/"):
                        p = p[1:]
                    self.base_dir = os.path.normpath(p)
                else:
                    self.base_dir = base_url
            else:
                self.base_dir = "."
        self.base_dir = os.path.abspath(self.base_dir)
        self.watch_base_dir = os.path.realpath(self.base_dir)

        # D7: Root & ignored defaults matching TS Hmr.Config
        self.root = list(self.config.get("root", ["."]))
        default_ignored = ["**/node_modules/**", "**/.*", "cache", "data", "**/.venv/**", "**/__pycache__/**", "**/.git/**", "**/dist/**", "**/.pytest_cache/**"]
        user_ignored = list(self.config.get("ignored", []))
        self.ignored = list(set(default_ignored + user_ignored))

        # D1: Externals matching TS index.ts:220-226
        self.externals: Set[str] = set()
        try:
            if sys.argv and sys.argv[0]:
                main_f = os.path.realpath(sys.argv[0])
                if os.path.isfile(main_f):
                    import pathlib
                    self.externals.add(pathlib.Path(main_f).as_uri())
        except Exception:
            pass

        self._stashed: Set[str] = set()
        self._debounce_handle: Optional[asyncio.TimerHandle] = None
        self._root_mtimes: Dict[str, float] = {}
        self._initial_scanned = False

        # Start background polling timer for portable zero-dependency Windows 7 file watching
        try:
            loop = asyncio.get_running_loop()
            self._poll_task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    async def init(self):
        """Service.init owns watcher shutdown and every pending refresh pass."""
        yield self._async_teardown

    def is_ignored(self, filepath: str, base_dir: str) -> bool:
        import fnmatch
        try:
            rel = os.path.relpath(filepath, base_dir).replace("\\", "/")
        except ValueError:
            rel = filepath.replace("\\", "/")
        name = os.path.basename(filepath)
        if name.startswith(".") or name in ("node_modules", "__pycache__", "dist", "build", ".venv", "venv", "cache", "data"):
            return True
        for pat in self.ignored:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(f"**/{name}", pat) or fnmatch.fnmatch(f"**/{rel}", pat):
                return True
            pat_stripped = pat.strip("*/")
            if pat_stripped and (pat_stripped in rel.split("/") or pat_stripped == name):
                return True
        return False

    def _schedule_partial_reload(self) -> None:
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None

        def _on_timeout():
            self._debounce_handle = None
            if self._stashed:
                stashed_files = list(self._stashed)
                self._stashed.clear()
                for f in stashed_files:
                    self._trigger_module_reload(f, self._modules.get(f))

        try:
            loop = asyncio.get_running_loop()
            self._debounce_handle = loop.call_later(max(0.01, self.debounce_ms / 1000.0), _on_timeout)
        except RuntimeError:
            _on_timeout()

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(max(0.02, self.debounce_ms / 1000.0))

                # 1. Check registered config files
                for filename, refresh_fn in list(self._configs.items()):
                    observed = self._config_names.get(filename, filename)
                    exists = os.path.exists(filename)
                    last_info = self._mtimes.get(filename)
                    last_mtime, last_size = last_info if isinstance(last_info, tuple) else (last_info or 0.0, -1)
                    if exists:
                        try:
                            stat = os.stat(filename)
                            mtime, size = stat.st_mtime, stat.st_size
                        except OSError:
                            continue

                        changed = False
                        if last_mtime == 0.0:  # add event
                            changed = True
                        elif mtime != last_mtime or size != last_size:  # change event
                            changed = True
                        else:
                            try:
                                with open(filename, "rb") as f:
                                    curr_content = f.read()
                                if curr_content != self._config_contents.get(filename):
                                    changed = True
                            except OSError:
                                pass

                        if changed:
                            try:
                                with open(filename, "rb") as f:
                                    self._config_contents[filename] = f.read()
                            except OSError:
                                pass
                            self._mtimes[filename] = (mtime, size)
                            self._trigger_config_refresh(filename, refresh_fn, observed)
                    else:
                        if last_mtime > 0.0:  # unlink event
                            self._config_contents.pop(filename, None)
                            self._mtimes[filename] = (0.0, -1)
                            self._trigger_config_refresh(filename, refresh_fn, observed)

                # 2. Check registered module files
                for filename, target_plugin in list(self._modules.items()):
                    exists = os.path.exists(filename)
                    last_info = self._mtimes.get(filename)
                    last_mtime, last_size = last_info if isinstance(last_info, tuple) else (last_info or 0.0, -1)
                    if exists:
                        try:
                            stat = os.stat(filename)
                            mtime, size = stat.st_mtime, stat.st_size
                        except OSError:
                            continue
                        if last_mtime != 0.0 and (mtime != last_mtime or size != last_size):  # change event only
                            self._mtimes[filename] = (mtime, size)
                            self._trigger_module_reload(filename, target_plugin)
                        elif last_mtime == 0.0:
                            self._mtimes[filename] = (mtime, size)
                    else:
                        if last_mtime > 0.0:
                            self._mtimes[filename] = (0.0, -1)

                # 3. Check roots
                if self.root:
                    import pathlib
                    for r in self.root:
                        scan_dir = os.path.realpath(os.path.join(self.watch_base_dir, r))
                        if not os.path.exists(scan_dir):
                            continue
                        if os.path.isdir(scan_dir):
                            for root_path, dirs, files in os.walk(scan_dir):
                                dirs[:] = [d for d in dirs if not self.is_ignored(os.path.join(root_path, d), scan_dir)]
                                for f in files:
                                    full_path = os.path.join(root_path, f)
                                    if self.is_ignored(full_path, scan_dir):
                                        continue
                                    try:
                                        mtime = os.path.getmtime(full_path)
                                        size = os.path.getsize(full_path)
                                    except OSError:
                                        continue
                                    if not self._initial_scanned:
                                        self._root_mtimes[full_path] = (mtime, size)
                                        continue
                                    last_info = self._root_mtimes.get(full_path)
                                    if last_info is not None:
                                        last_m, last_sz = last_info
                                        if mtime > last_m or size != last_sz:
                                            self._root_mtimes[full_path] = (mtime, size)
                                            url = pathlib.Path(os.path.realpath(full_path)).as_uri()

                                            # D17: Match include subtree
                                            loader = getattr(self.ctx, "loader", None)
                                            matched_include = False
                                            if loader and hasattr(loader, "entries"):
                                                for entry in list(loader.entries()):
                                                    include = getattr(entry, "subtree", None)
                                                    inc_fn = getattr(include, "filename", None)
                                                    if inc_fn and os.path.realpath(full_path) == os.path.realpath(inc_fn):
                                                        self._trigger_config_refresh(inc_fn, lambda inc=include: inc.refresh())
                                                        matched_include = True
                                                        break
                                            if matched_include:
                                                continue

                                            # D1: Match externals -> loader.exit()
                                            if url in self.externals:
                                                if loader and hasattr(loader, "exit"):
                                                    loader.exit()
                                                    return
                                                continue

                                            # D2: Match loadCache -> stashed partial reload
                                            internal = getattr(loader, "internal", None) if loader else None
                                            load_cache = getattr(internal, "loadCache", None) if internal else None
                                            in_cache = False
                                            if load_cache is not None and hasattr(load_cache, "has"):
                                                in_cache = load_cache.has(url)

                                            if in_cache:
                                                self._stashed.add(full_path)
                                                self._schedule_partial_reload()
                                            elif hasattr(self.ctx, "emit"):
                                                self.ctx.emit("hmr/change", url)
                                    elif last_info is None:
                                        self._root_mtimes[full_path] = (mtime, size)
                    self._initial_scanned = True

            except asyncio.CancelledError:
                break
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("Exception in poll loop: %s", e)

    def _trigger_config_refresh(self, filename: str, refresh_fn: Callable[[], Any],
                                observed: Optional[str] = None) -> None:
        """Run a refresh keyed by `filename`, broadcasting `observed` as the watched path."""
        if observed is None:
            observed = filename
        state = self._refreshes.setdefault(filename, ConfigRefreshState())
        state.dirty = True
        if state.running and not state.running.done():
            return

        async def _run() -> None:
            while state.dirty:
                state.dirty = False
                try:
                    res = refresh_fn()
                    if inspect.isawaitable(res):
                        await res
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded config file %s", observed)
                except asyncio.CancelledError:
                    raise
                except Exception as reason:
                    error = reason
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").warn("config reload at %s failed", observed)
                        self.ctx.logger("hmr").warn("%s", error)
                    if hasattr(self.ctx, "parallel"):
                        try:
                            await self.ctx.parallel("hmr/config-update-failed", observed, error)
                        except Exception as rejection:
                            if hasattr(self.ctx, "logger"):
                                self.ctx.logger("hmr").warn("%s", rejection)

                # The root owns the registration disposer, which joins this
                # pass. Waiting for root teardown here would create a cycle.
                # Its caller joins root settlement after this pass completes.

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_run())
            state.running = task
            self._refresh_tasks.add(task)
            task.add_done_callback(lambda t: self._refresh_tasks.discard(t))
        except RuntimeError:
            try:
                res = refresh_fn()
                if inspect.isawaitable(res):
                    asyncio.run(res)
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").info("Reloaded config file %s", observed)
            except Exception as reason:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("config reload at %s failed: %s", observed, reason)

    def _trigger_module_reload(self, filename: str, target_plugin: Optional[Any]) -> None:
        """
        Coalesce module changes into one running reload pass.

        `hmr` runs one debounced partial reload for the whole service, so a change
        detected while a pass is running joins that pass instead of starting a
        second one. Each pass awaits fiber disposal and remount, so overlapping
        passes would reload one runtime twice and roll back only their own slice:
        the multi-file rollback would leave the other file on its replacement.
        """
        refresh_state = self._refreshes.setdefault(filename, ConfigRefreshState())
        refresh_state.dirty = True
        self._module_changes[os.path.abspath(filename)] = target_plugin
        if self._module_reload_task is not None and not self._module_reload_task.done():
            return

        async def _reload_one(filename: str, target_plugin: Optional[Any]) -> None:
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
                prev_runtimes = dict(registry._runtimes) if registry else {}
                saved_runtimes_state: Dict[Any, Dict[str, Any]] = {}
                if registry:
                    for r_key, r_val in registry._runtimes.items():
                        saved_runtimes_state[r_key] = {
                            "callback": r_val.callback,
                            "runtime": r_val,
                            "fibers": [
                                (f, getattr(f, "_plugin_cls", None), getattr(f, "plugin", None), getattr(f, "config", None))
                                for f in list(getattr(r_val, "fibers", []))
                            ],
                        }
                saved_fibers: Dict[Any, List[Any]] = {}

                async def reload_plugin(plugin_target: Any, r_time: Any, old_key: Any = None) -> None:
                    if not r_time:
                        return
                    target_fibers = (saved_fibers.get(old_key) if old_key else None) or list(getattr(r_time, "fibers", []))
                    for old_fiber in list(target_fibers):
                        parent = getattr(old_fiber, "parent", None) or self.ctx
                        reg = getattr(parent, "registry", None) or getattr(self.ctx, "registry", None)
                        new_fiber = reg.plugin(plugin_target, getattr(old_fiber, "config", None))
                        # The mount returns while the replacement fiber is
                        # LOADING; the swap below needs its instantiated plugin
                        # and must observe an apply failure to trigger rollback.
                        await_fn = getattr(new_fiber, "await_settled", None) or getattr(new_fiber, "await_", None)
                        if await_fn is not None:
                            await await_fn()
                        err = getattr(new_fiber, "_error", None) or getattr(new_fiber, "error", None)
                        if err is not None:
                            raise err
                        new_fiber.entry = getattr(old_fiber, "entry", None)
                        if new_fiber.entry:
                            new_fiber.entry.fiber = new_fiber
                        old_fiber._plugin_cls = plugin_target
                        old_fiber.plugin = new_fiber.plugin

                new_modules_created: List[str] = []
                try:
                    for file_path in files_to_reload:
                        if not os.path.isfile(file_path):
                            continue

                        # Dynamic reload Python module
                        importlib.invalidate_caches()
                        mod_name = f"hmr_reloaded_{abs(hash(file_path))}_{int(time.time() * 1000)}"
                        mod = types.ModuleType(mod_name)
                        mod.__file__ = file_path
                        sys.modules[mod_name] = mod
                        new_modules_created.append(mod_name)
                        with open(file_path, "r", encoding="utf-8") as fp:
                            source_code = fp.read()
                        code_obj = compile(source_code, file_path, "exec")
                        exec(code_obj, mod.__dict__)

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
                            r_entry = registry.get(old_key)
                            if r_entry and old_key not in saved_fibers:
                                saved_fibers[old_key] = list(getattr(r_entry, "fibers", []))

                        for old_key, new_cls in found_classes:
                            runtime = registry.get(old_key)
                            if runtime:
                                reloads[old_key] = {"filename": file_path, "runtime": runtime, "attempt": new_cls}
                                try:
                                    await registry.delete_async(old_key)
                                except Exception as err:
                                    if hasattr(self.ctx, "logger"):
                                        self.ctx.logger("hmr").warn("failed to dispose plugin %s: %s", old_key, err)

                                try:
                                    await reload_plugin(new_cls, runtime, old_key)
                                    if hasattr(self.ctx, "logger"):
                                        self.ctx.logger("hmr").info("reload plugin %s", new_cls)
                                except Exception as err:
                                    if hasattr(self.ctx, "logger"):
                                        self.ctx.logger("hmr").warn("failed to reload plugin %s: %s", new_cls, err)
                                    raise err
                except Exception as step_err:
                    for m_name in new_modules_created:
                        sys.modules.pop(m_name, None)
                    if registry:
                        for old_key, info in reloads.items():
                            runtime = info.get("runtime")
                            attempt = info.get("attempt")
                            if not runtime:
                                continue
                            try:
                                if attempt:
                                    await registry.delete_async(attempt)
                                await reload_plugin(old_key, runtime, old_key)
                            except Exception as err:
                                if hasattr(self.ctx, "logger"):
                                    self.ctx.logger("hmr").warn("failed during rollback of %s: %s", old_key, err)
                    raise step_err

                if reloads and hasattr(self.ctx, "emit"):
                    self.ctx.emit("hmr/reload", reloads)

                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").info("Reloaded module %s (%d plugins affected)", filename, len(reloads))

            except Exception as reason:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("Module reload at %s failed: %s", filename, reason)

        async def _run() -> None:
            while self._module_changes:
                pending = list(self._module_changes.items())
                self._module_changes.clear()
                for changed_file, changed_target in pending:
                    state = self._refreshes.get(changed_file)
                    if state is not None:
                        state.dirty = False
                    await _reload_one(changed_file, changed_target)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_run())
            self._module_reload_task = task
            for state in self._refreshes.values():
                if state.dirty:
                    state.running = task
            self._refresh_tasks.add(task)
            task.add_done_callback(lambda t: self._refresh_tasks.discard(t))
        except RuntimeError:
            pass

    def register_config(self, filename: str, refresh_fn: Callable[[], Any]) -> Any:
        """
        Watch one exact config path and execute refresh_fn on modification matching TS hmr.registerConfig.
        """
        if not self._running:
            raise RuntimeError("HMR is not active")

        filename = os.path.abspath(os.path.join(self.base_dir, filename))

        canonical_filename, canonical_root, depth = find_watch_root(filename)
        if canonical_filename in self._configs:
            raise ValueError(f"config path already registered: {filename}")
        self._config_names[canonical_filename] = filename

        if os.path.exists(canonical_filename):
            try:
                stat = os.stat(canonical_filename)
                self._mtimes[canonical_filename] = (stat.st_mtime, stat.st_size)
                with open(canonical_filename, "rb") as f:
                    self._config_contents[canonical_filename] = f.read()
            except OSError:
                self._mtimes[canonical_filename] = (0.0, -1)
            # Present file at registration: trigger refresh once matching TS ignoreInitial: false
            self._trigger_config_refresh(canonical_filename, refresh_fn, filename)
        else:
            self._mtimes[canonical_filename] = (0.0, -1)

        self._configs[canonical_filename] = refresh_fn

        class ConfigDisposer:
            def __init__(self, hmr_svc: Any, c_filename: str):
                self.hmr = hmr_svc
                self.canonical_filename = c_filename
                self.disposed = False
                self._task = None

            def __call__(self) -> Any:
                self.hmr._configs.pop(self.canonical_filename, None)
                self.hmr._config_names.pop(self.canonical_filename, None)
                self.hmr._mtimes.pop(self.canonical_filename, None)
                self.hmr._config_contents.pop(self.canonical_filename, None)
                state = self.hmr._refreshes.get(self.canonical_filename)

                async def _run() -> None:
                    if state and state.running and not state.running.done():
                        await asyncio.shield(state.running)
                    self.hmr._refreshes.pop(self.canonical_filename, None)
                    self.disposed = True

                try:
                    loop = asyncio.get_running_loop()
                    self._task = loop.create_task(_run())
                except RuntimeError:
                    self.disposed = True
                return self

            def __await__(self) -> Any:
                if self._task is not None:
                    return self._task.__await__()
                self.__call__()
                if self._task is not None:
                    return self._task.__await__()

                async def _dummy() -> None:
                    return None

                return _dummy().__await__()

        disposer = ConfigDisposer(self, canonical_filename)
        if hasattr(self.ctx, "effect"):
            self.ctx.effect(lambda: disposer, label=f"hmr.registerConfig('{canonical_filename}')")

        class RegistrationPromise:
            def __init__(self, disp: Any):
                self._disp = disp

            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                return self._disp(*args, **kwargs)

            def __await__(self) -> Any:
                async def _ready() -> Any:
                    return self._disp

                return _ready().__await__()

            def __getattr__(self, name: str) -> Any:
                return getattr(self._disp, name)

        return RegistrationPromise(disposer)

    registerConfig = register_config

    def register_module(self, filename: str, plugin_cls: Optional[Any] = None) -> Callable[[], None]:
        """
        Watch a Python module file and dynamically reload its plugins on modification matching TS Hmr module watch.
        """
        if not self._running:
            raise RuntimeError("HMR is not active")

        abs_path = os.path.abspath(filename)
        if os.path.exists(abs_path):
            try:
                st = os.stat(abs_path)
                self._mtimes[abs_path] = (st.st_mtime, st.st_size)
            except OSError:
                self._mtimes[abs_path] = (0.0, -1)
        else:
            self._mtimes[abs_path] = (0.0, -1)

        self._modules[abs_path] = plugin_cls
        self.graph.scan_file(abs_path)

        def unregister() -> None:
            self._modules.pop(abs_path, None)
            self._mtimes.pop(abs_path, None)
            state = self._refreshes.pop(abs_path, None)
            if state and state.running and not state.running.done():
                async def _wait():
                    try:
                        await state.running
                    except Exception:
                        pass
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                # `fiber.ts` keeps driving a dropped awaitable; CPython needs
                # an owner, so the fiber records this join of the running pass.
                fiber = getattr(self.ctx, "fiber", None) if self.ctx is not None else None
                if fiber is not None and hasattr(fiber, "schedule_settlement"):
                    fiber.schedule_settlement(_wait())
                else:
                    loop.create_task(_wait())

        if hasattr(self.ctx, "disposable"):
            return self.ctx.disposable(unregister, label=f"hmr.register_module('{abs_path}')")
        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: unregister, label=f"hmr.register_module('{abs_path}')")
        return unregister

    registerModule = register_module

    async def _async_teardown(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        if self._poll_task is not None:
            await asyncio.gather(self._poll_task, return_exceptions=True)
        running_tasks = [s.running for s in self._refreshes.values() if s and s.running and not s.running.done()]
        running_tasks.extend([t for t in self._refresh_tasks if not t.done()])
        if running_tasks:
            try:
                await asyncio.gather(*running_tasks, return_exceptions=True)
            except Exception:
                pass
        self._configs.clear()
        self._config_names.clear()
        self._modules.clear()
        self._mtimes.clear()
        self._root_mtimes.clear()

    def teardown(self) -> Optional[asyncio.Task]:
        """
        Start the teardown `init` owns and give its settlement an owner.

        `reference/vendor/hmr/src/index.ts:199-205` owns this teardown as the
        `Service.init` disposer, which the service fiber awaits. A synchronous
        caller inside a running loop cannot await it, so the fiber owns the
        settlement the same way `Context.teardown()` does: `await_settled()`
        and `settle_fibers()` join it, and a caller that must observe
        quiescence awaits the returned task. With no running loop the
        settlement runs inline and there is nothing left to join.

        @returns the owned settlement task, or `None` after an inline run.
        """
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        settlement = self._async_teardown()
        fiber = getattr(self.ctx, "fiber", None) if self.ctx is not None else None
        if fiber is not None and hasattr(fiber, "schedule_settlement"):
            return fiber.schedule_settlement(settlement)
        # A context without an owning fiber has nowhere to record the
        # settlement, so the teardown still runs with no owner to join it.
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(settlement)
        except RuntimeError:
            asyncio.run(settlement)
            return None


# Backward-compatible and alias names
Hmr = ConfigWatcherService
HmrService = ConfigWatcherService
