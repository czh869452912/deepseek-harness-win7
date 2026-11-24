"""
Cordis Config Watcher & HMR Service matching reference/vendor/hmr/src/index.ts.
Provides safe configuration and module watching, debouncing, serialized refreshes,
dynamic Python module reload, and 'hmr/change', 'hmr/reload', 'hmr/config-update-failed' events.
"""

import asyncio
import contextvars
import errno
import importlib
import importlib.util
import importlib.abc
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
from dsh.cordis.hmr_files import ModuleFiles
from dsh.cordis.hmr_paths import file_path, profile_roots
from dsh.cordis.hmr_modules import PythonModules


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
                        if not mod_name:
                            for alias in node.names:
                                child = self._resolve_relative(alias.name, target_dir)
                                if child:
                                    imported_files.add(child)
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


class ConfigRegistration:
    """
    One exact-path config watch, matching `registerConfig` in
    `reference/vendor/hmr/src/index.ts:60-62,134-187`.

    The registration object is the identity key of its own refresh state:
    upstream stores that state in `configRefreshes = new WeakMap<object,
    ConfigRefresh>` (`index.ts:93-95,296-320`), so a module watch disposed for
    the same path can never retire the live config watch's serialization state.
    Disposal joins and retires exactly the pass this registration owns
    (`index.ts:177-181`).
    """

    def __init__(self, hmr: "ConfigWatcherService", canonical_filename: str,
                 observed: str, refresh_fn: Callable[[], Any]):
        self.hmr = hmr
        self.canonical_filename = canonical_filename
        # Path handed to the refresh callback and the failure event, matching
        # the `filename` argument of `refreshConfig` (`index.ts:154,297-312`).
        self.observed = observed
        self.refresh = refresh_fn
        self.state = ConfigRefreshState()
        self.disposed = False
        self._task: Optional[asyncio.Task] = None
        self.reserved_paths = []
        self.legacy = True

    def __call__(self) -> Any:
        # Retire this registration only while it still owns the path, then join
        # its own running pass (`index.ts:177-181`). Another registration's
        # refresh state for the same path is left untouched.
        if self.hmr._configs.get(self.canonical_filename) is self:
            self.hmr._configs.pop(self.canonical_filename, None)
        self.hmr._mtimes.pop(self.canonical_filename, None)
        self.hmr._config_contents.pop(self.canonical_filename, None)
        state = self.hmr._config_refreshes.get(self)

        async def _run() -> None:
            if state is not None and state.running and not state.running.done() and not self.hmr._executing.get():
                await asyncio.shield(state.running)
            if state is not None and self.hmr._config_refreshes.get(self) is state:
                self.hmr._config_refreshes.pop(self, None)
            self.disposed = True
            for path in self.reserved_paths:
                self.hmr._config_paths.discard(path)

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
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
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
        self._owner_context = ctx
        self._operations = None
        self._executing = contextvars.ContextVar('hmr_transaction', default=False)
        self._closing = False
        self._config_paths = set()
        self.files = ModuleFiles()
        self._application_ready = None
        self._cancel_ready = None
        self.modules = PythonModules(ctx)

        # D8: Verify loader and internal
        loader = self.ctx.get("loader")
        if loader is not None and not getattr(loader, "internal", None):
            raise RuntimeError("--expose-internals is required for HMR service")

        self.debounce_ms: float = float(self.config.get("debounce", 100))
        self._configs: Dict[str, ConfigRegistration] = {}
        self._modules: Dict[str, Optional[Any]] = {}
        # Config and module watches keep separate staleness entries: the config
        # loop reads a missing entry as an add event, so a shared key would let a
        # disposed module registration re-arm a live config watch.
        self._mtimes: Dict[str, Tuple[float, int]] = {}
        self._module_mtimes: Dict[str, Tuple[float, int]] = {}
        self._config_contents: Dict[str, bytes] = {}
        # Refresh state is keyed by the registration that owns it: config state
        # by the `ConfigRegistration` object (`index.ts:93-95` WeakMap), module
        # state by the watched module path. A module registration can therefore
        # never retire a live config registration's serialization state.
        self._config_refreshes: Dict[Any, ConfigRefreshState] = {}
        self._module_refreshes: Dict[str, ConfigRefreshState] = {}
        # One serialized module-reload pass plus its pending changed files, so a
        # change detected mid-pass joins that pass instead of racing it.
        self._module_reload_task: Optional[asyncio.Task] = None
        self._module_changes: Dict[str, Any] = {}
        self._refresh_tasks: Set[asyncio.Task] = set()
        self.graph = ModuleDependencyGraph()
        self._poll_task: Optional[asyncio.Task] = None
        self._running = True

        from urllib.parse import urljoin
        base_url = getattr(ctx, 'baseUrl', None) or getattr(ctx, 'base_url', None)
        configured_base = self.config.get('base') or '.'
        if base_url and base_url.startswith('file:'):
            self.base_dir = os.path.abspath(file_path(urljoin(base_url, configured_base)))
        else:
            self.base_dir = os.path.abspath(os.path.join(base_url or '.', configured_base))
        self.watch_base_dir = os.path.realpath(self.base_dir)
        self.root = list(self.config.get('root', ['.']))
        self.ignored = list(self.config.get('ignored', ['**/node_modules', '**/.*', 'cache', 'data']))
        self.externals = set()
        self._watch_started = False

        self._changed = {}
        self._stashed = {}
        self._debounce_handle: Optional[asyncio.TimerHandle] = None
        self._root_mtimes: Dict[str, float] = {}
        self._root_unlinks = {}
        self._root_unlink_deadlines = []
        self._root_writes = {}
        self._root_emitted = {}
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
        profile = self._owner_context.get('profileContext')
        if profile is not None:
            ready = self._owner_context.get('appReady')
            if ready is None:
                raise RuntimeError('Profile HMR requires application readiness')
            started = asyncio.get_running_loop().create_future()
            self._application_ready = started
            def on_ready():
                try:
                    from dsh.boot.runtime_resolution import _field
                    self.files.observe(self._profile_modules(profile_roots(_field(profile, 'dir'))))
                except Exception as error:
                    self.ctx.logger.warn(error)
                if not started.done():
                    started.set_result(True)
            subscribe = getattr(ready, 'onReady', None) or ready.on_ready
            unsubscribe = subscribe(on_ready)
            def cancel_ready():
                self._cancel_ready = None
                unsubscribe()
                if not started.done():
                    started.set_result(False)
            self._cancel_ready = cancel_ready
            owner_fiber = self._owner_context.fiber
            def retiring(fiber):
                # Release the startup barrier when disposal starts, before watchers
                # join callbacks that are waiting on that barrier.
                if fiber is owner_fiber and fiber.uid is None and self._cancel_ready is not None:
                    self._cancel_ready()
            self._owner_context.on('internal/plugin', retiring, global_listener=True)
            yield cancel_ready
            from dsh.cordis.hmr_profile_watch import watch_profile
            await watch_profile(self, profile)
        from dsh.cordis.hmr_root_watch import scan
        from dsh.cordis.hmr_glob import _compile
        # Like Chokidar's ready event, the initial inventory precedes service
        # activation. Root changes cannot race an uninitialized classifier.
        os.stat(self.watch_base_dir)
        for pattern in self.ignored:
            _compile(pattern[1:] if pattern.startswith('!') and not pattern.startswith('!(') else pattern)
        self.externals = self.modules.external_modules()
        await scan(self, initial=True)
        self._watch_started = True

    def _profile_modules(self, roots):
        """Loaded Python modules below the profile and its linked packages."""
        return [url for url in self.modules.loaded_urls()
                if isinstance(url, str) and url.startswith('file:')
                and any(file_path(url).startswith(root) for root in roots)]

    async def get_linked(self, url):
        return self.modules.get_linked(url)

    getLinked = get_linked

    async def analyze_changes(self):
        from dsh.cordis.hmr_changes import analyze_changes
        await analyze_changes(self)

    analyzeChanges = analyze_changes

    async def reconcile_profile(self, required_ids=()):
        from dsh.cordis.hmr_profile import reconcile_profile
        return await reconcile_profile(self, required_ids)

    reconcileProfile = reconcile_profile

    def run_exclusive(self, operation):
        """Append a caller mutation to the reload queue, preserving its result."""
        loop = asyncio.get_running_loop()
        if self._executing.get():
            result = loop.create_future()
            result.set_exception(RuntimeError('HMR transactions cannot be nested'))
            return result
        previous = self._operations
        async def execute():
            if previous is not None:
                await asyncio.gather(previous, return_exceptions=True)
            if self._closing:
                raise RuntimeError('HMR is disposed')
            token = self._executing.set(True)
            try:
                result = operation()
                return await result if inspect.isawaitable(result) else result
            finally:
                self._executing.reset(token)
        task = loop.create_task(execute())
        self._operations = task
        # The service owns queued work, even when its caller abandons a wait.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return asyncio.shield(task)

    runExclusive = run_exclusive

    async def _run_reload(self, operation):
        async def reload_when_ready():
            if self._application_ready is not None and not await asyncio.shield(self._application_ready):
                return
            result = operation()
            return await result if inspect.isawaitable(result) else result
        return await self.run_exclusive(reload_when_ready)

    async def watch_config(self, filename, refresh):
        paths = {os.path.abspath(filename), os.path.realpath(filename)}
        if self._config_paths.intersection(paths):
            raise ValueError('config path already registered: '+filename)
        self._config_paths.update(paths)
        token = self._executing.set(False)
        try:
            registration = await self.register_config(filename, refresh, paths)
            registration.legacy = False
            return registration
        except BaseException:
            self._config_paths.difference_update(paths)
            raise
        finally:
            self._executing.reset(token)

    watchConfig = watch_config

    def is_ignored(self, filepath: str, base_dir: str) -> bool:
        from dsh.cordis.hmr_glob import matches
        relative = os.path.relpath(filepath, base_dir)
        # Upstream passes path.relative directly to picomatch, including native
        # Windows separators. Its root-relative empty path is not a dotfile.
        return matches('' if relative == '.' else relative, self.ignored)

    def invalidate_manifest(self, filename):
        # Python profile/resource metadata reads are uncached. Directory finder
        # caches still need expiry when package files are replaced in place.
        importlib.invalidate_caches()

    async def partial_reload(self):
        from dsh.cordis.hmr_partial import partial_reload
        await partial_reload(self)

    partialReload = partial_reload

    def _module_changed(self, path):
        self._changed[path] = None
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
        def dispatch():
            self._debounce_handle = None
            from dsh.cordis.hmr_dispatch import dispatch as dispatch_batch
            task = self.run_exclusive(lambda: dispatch_batch(self))
            self._refresh_tasks.add(task)
            def done(result):
                self._refresh_tasks.discard(result)
                if not result.cancelled() and result.exception() is not None:
                    self.ctx.logger.warn(result.exception())
            task.add_done_callback(done)
        loop = asyncio.get_running_loop()
        token = self._executing.set(False)
        try:
            self._debounce_handle = loop.call_later(max(0, self.debounce_ms / 1000.0), dispatch)
        finally:
            self._executing.reset(token)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                # Debounce combines notifications; it must not delay observing
                # the filesystem or joining exact configuration changes.
                await asyncio.sleep(0.02)

                # 1. Check registered config files
                for filename, registration in list(self._configs.items()):
                    observed = registration.observed
                    last_info = self._mtimes.get(filename)
                    last_mtime, last_size = last_info if isinstance(last_info, tuple) else (last_info or 0.0, -1)
                    try:
                        metadata = os.stat(filename)
                    except OSError:
                        if last_mtime > 0.0 and not os.path.exists(filename):
                            self._config_contents.pop(filename, None)
                            self._mtimes[filename] = (0.0, -1)
                            self._trigger_config_refresh(
                                registration, filename, registration.refresh, observed)
                        continue

                    stamp = (metadata.st_mtime, metadata.st_size)
                    changed = last_mtime == 0.0 or stamp != (last_mtime, last_size)
                    try:
                        with open(filename, "rb") as stream:
                            content = stream.read()
                    except OSError:
                        pass
                    else:
                        changed = changed or content != self._config_contents.get(filename)
                        if changed:
                            self._config_contents[filename] = content
                    if changed:
                        self._mtimes[filename] = stamp
                        self._trigger_config_refresh(
                            registration, filename, registration.refresh, observed)

                # 2. Check registered module files
                for filename, target_plugin in list(self._modules.items()):
                    last_info = self._module_mtimes.get(filename)
                    last_mtime, last_size = last_info if isinstance(last_info, tuple) else (last_info or 0.0, -1)
                    try:
                        metadata = os.stat(filename)
                    except OSError:
                        if last_mtime > 0.0 and not os.path.exists(filename):
                            self._module_mtimes[filename] = (0.0, -1)
                        continue
                    stamp = (metadata.st_mtime, metadata.st_size)
                    if last_mtime == 0.0:
                        self._module_mtimes[filename] = stamp
                    elif stamp != (last_mtime, last_size):
                        self._module_mtimes[filename] = stamp
                        self._trigger_module_reload(filename, target_plugin)

                if self._watch_started and self.root:
                    from dsh.cordis.hmr_root_watch import scan
                    await scan(self)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("Exception in poll loop: %s", e)

    def _config_refresh_state(self, key: Any) -> ConfigRefreshState:
        """
        Return the refresh state owned by `key`, creating it on first use.

        A `ConfigRegistration` owns the state object its disposer joins and
        retires (`index.ts:93-95,177-181`); a loader include entry keys its own
        state the same way (`index.ts:252,297-299`).
        """
        state = self._config_refreshes.get(key)
        if state is None:
            state = getattr(key, "state", None)
            if not isinstance(state, ConfigRefreshState):
                state = ConfigRefreshState()
            self._config_refreshes[key] = state
        return state

    def _trigger_config_refresh(self, key: Any, filename: str, refresh_fn: Callable[[], Any],
                                observed: Optional[str] = None) -> None:
        """
        Run one registration's serialized refresh pass.

        `reference/vendor/hmr/src/index.ts:296-324` keys the state by the
        registration object, marks it dirty, and returns while a pass runs, so
        later events coalesce into that pass instead of starting a second
        callback for the same registration.
        """
        if observed is None:
            observed = filename
        state = self._config_refresh_state(key)
        state.dirty = True
        if state.running and not state.running.done():
            return

        async def _run() -> None:
            while state.dirty:
                state.dirty = False
                try:
                    await self._run_reload(refresh_fn)
                    if getattr(key, 'legacy', True) and hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded config file %s", observed)
                except asyncio.CancelledError:
                    raise
                except Exception as reason:
                    error = reason
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").warn("config reload at %s failed", observed)
                        self.ctx.logger("hmr").warn("%s", error)
                    if getattr(key, 'legacy', True) and hasattr(self.ctx, "parallel"):
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
            token = self._executing.set(False)
            try:
                task = loop.create_task(_run())
            finally:
                self._executing.reset(token)
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
        refresh_state = self._module_refreshes.setdefault(filename, ConfigRefreshState())
        refresh_state.dirty = True
        self._module_changes[os.path.abspath(filename)] = target_plugin
        if self._module_reload_task is not None and not self._module_reload_task.done():
            return

        async def _run() -> None:
            try:
                while self._module_changes:
                    pending = list(self._module_changes.items())
                    self._module_changes.clear()
                    for changed_file, changed_target in pending:
                        state = self._module_refreshes.get(changed_file)
                        if state is not None:
                            state.dirty = False
                    await self._run_reload(lambda: self._reload_module_batch(pending))
            except Exception as error:
                if hasattr(self.ctx, 'logger'):
                    self.ctx.logger('hmr').warn('%s', error)
            finally:
                # The pass drops its own serialization state in its `finally`
                # (`index.ts:318-321`), so a settled pass is never a join target.
                for owned in self._module_refreshes.values():
                    if owned.running is task:
                        owned.running = None

        try:
            loop = asyncio.get_running_loop()
            token = self._executing.set(False)
            try:
                task = loop.create_task(_run())
            finally:
                self._executing.reset(token)
            self._module_reload_task = task
            for state in self._module_refreshes.values():
                if state.dirty:
                    state.running = task
            self._refresh_tasks.add(task)
            task.add_done_callback(lambda t: self._refresh_tasks.discard(t))
        except RuntimeError:
            pass

    async def _reload_module_batch(self, changes: List[Tuple[str, Any]]) -> None:
        reloads: Dict[Any, Dict[str, Any]] = {}
        targets = {os.path.abspath(path): plugin for path, plugin in changes}
        filename = ", ".join(targets)
        try:
            files_to_reload: List[str] = []
            for changed in targets:
                if hasattr(self.ctx, "emit"):
                    self.ctx.emit("hmr/change", changed)
                self.graph.scan_file(changed)
                dependents = self.graph.get_transitive_dependents(changed)
                for path in [changed] + list(reversed(dependents)):
                    if path not in files_to_reload:
                        files_to_reload.append(path)
            registry = getattr(self.ctx, "registry", None)
            saved_fibers: Dict[Any, List[Any]] = {}

            async def reload_plugin(plugin_target: Any, r_time: Any, old_key: Any = None) -> None:
                if not r_time:
                    return
                target_fibers = (saved_fibers.get(old_key) if old_key else None) or list(getattr(r_time, "fibers", []))
                for old_fiber in list(target_fibers):
                    parent = getattr(old_fiber, "parent", None) or self.ctx
                    reg = getattr(parent, "registry", None) or getattr(self.ctx, "registry", None)
                    new_fiber = reg.plugin(plugin_target, getattr(old_fiber, "config", None))
                    # Upstream HMR registers replacements without awaiting
                    # startup. Apply rejection is a FAILED replacement, not
                    # a synchronous registration failure requiring rollback.
                    new_fiber.entry = getattr(old_fiber, "entry", None)
                    if new_fiber.entry:
                        new_fiber.entry.fiber = new_fiber

            new_modules_created: List[str] = []
            cache_backup: Dict[str, Any] = {}
            loader = self.ctx.get("loader", None)
            load_cache = getattr(getattr(loader, "internal", None), "loadCache", {})
            loader_backup = dict(load_cache)
            prepared: Dict[str, Any] = {}
            parent_backup: List[Tuple[Any, str, Any]] = []
            try:
                # Remove the whole accepted module set before importing.
                # A temporary source loader supports Python cycles/relative
                # imports without stale pyc or references to an old sibling.
                importlib.invalidate_caches()
                names_by_path: Dict[str, List[str]] = {}
                paths_by_name: Dict[str, str] = {}
                parent_backup: List[Tuple[Any, str, Any]] = []
                for file_path in files_to_reload:
                    if not os.path.isfile(file_path):
                        raise FileNotFoundError(file_path)
                    aliases = [name for name, module in list(sys.modules.items())
                               if getattr(module, "__file__", None)
                               and os.path.realpath(module.__file__) == os.path.realpath(file_path)]
                    names_by_path[file_path] = aliases or ["hmr_reloaded_%s" % abs(hash(file_path))]
                    for name in names_by_path[file_path]:
                        paths_by_name[name] = file_path
                        if name in sys.modules:
                            cache_backup[name] = sys.modules.pop(name)
                        else:
                            new_modules_created.append(name)
                        parent_name, _, child = name.rpartition(".")
                        parent_module = sys.modules.get(parent_name)
                        if parent_module is not None and hasattr(parent_module, child):
                            parent_backup.append((parent_module, child, getattr(parent_module, child)))
                            delattr(parent_module, child)
                class SourceLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
                    def find_spec(self, fullname, path=None, target=None):
                        filename = paths_by_name.get(fullname)
                        if filename is None:
                            return None
                        return importlib.util.spec_from_file_location(fullname, filename, loader=self,
                            submodule_search_locations=[os.path.dirname(filename)]
                            if os.path.basename(filename) == "__init__.py" else None)
                    def create_module(self, spec):
                        return None
                    def exec_module(self, module):
                        with open(module.__spec__.origin, "r", encoding="utf-8") as stream:
                            code = compile(stream.read(), module.__spec__.origin, "exec")
                        exec(code, module.__dict__)
                source_loader = SourceLoader()
                sys.meta_path.insert(0, source_loader)
                try:
                    for file_path in files_to_reload:
                        aliases = names_by_path[file_path]
                        mod = importlib.import_module(aliases[0])
                        for alias in aliases:
                            sys.modules[alias] = mod
                        prepared[file_path] = mod
                        from pathlib import Path
                        load_cache[Path(os.path.realpath(file_path)).as_uri()] = mod
                finally:
                    sys.meta_path.remove(source_loader)
                for file_path in files_to_reload:
                    mod = prepared[file_path]
                    if not registry:
                        continue

                    # Find all plugin classes in module
                    found_classes: List[Tuple[Any, Any]] = []
                    tgt = targets.get(file_path) or self._modules.get(file_path)
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
                sys.modules.update(cache_backup)
                for parent_module, child, value in parent_backup:
                    setattr(parent_module, child, value)
                load_cache.clear()
                load_cache.update(loader_backup)
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

            # Future changes must target the replacement runtime, not the
            # disposed class retained by the original watch registration.
            for old_key, info in reloads.items():
                path = info["filename"]
                if self._modules.get(path) is old_key:
                    self._modules[path] = info["attempt"]
            if reloads and hasattr(self.ctx, "emit"):
                self.ctx.emit("hmr/reload", reloads)

            if hasattr(self.ctx, "logger"):
                self.ctx.logger("hmr").info("Reloaded module %s (%d plugins affected)", filename, len(reloads))

        except Exception as reason:
            if hasattr(self.ctx, "logger"):
                self.ctx.logger("hmr").warn("Module reload at %s failed: %s", filename, reason)


    def register_config(self, filename: str, refresh_fn: Callable[[], Any], _reserved_paths=None) -> Any:
        """
        Watch one exact config path and execute refresh_fn on modification matching TS hmr.registerConfig.
        """
        if not self._running:
            raise RuntimeError("HMR is not active")

        filename = os.path.abspath(os.path.join(self.base_dir, filename))

        canonical_filename, canonical_root, depth = find_watch_root(filename)
        if canonical_filename in self._configs:
            raise ValueError(f"config path already registered: {filename}")

        # `index.ts:149-155`: the registration owns the watch, the observed path
        # and the serialization state before the first refresh is scheduled.
        registration = ConfigRegistration(self, canonical_filename, filename, refresh_fn)
        registration.reserved_paths = [] if _reserved_paths is None else _reserved_paths
        registration.legacy = _reserved_paths is None

        if os.path.exists(canonical_filename):
            try:
                stat = os.stat(canonical_filename)
                self._mtimes[canonical_filename] = (stat.st_mtime, stat.st_size)
                with open(canonical_filename, "rb") as f:
                    self._config_contents[canonical_filename] = f.read()
            except OSError:
                self._mtimes[canonical_filename] = (0.0, -1)
            # Present file at registration: trigger refresh once matching TS ignoreInitial: false
            self._trigger_config_refresh(
                registration, canonical_filename, refresh_fn, filename)
        else:
            self._mtimes[canonical_filename] = (0.0, -1)

        self._configs[canonical_filename] = registration

        if hasattr(self.ctx, "effect"):
            try:
                self._owner_context.effect(lambda: registration,
                                label=f"hmr.registerConfig('{canonical_filename}')")
            except BaseException:
                registration()
                raise

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

        return RegistrationPromise(registration)

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
                self._module_mtimes[abs_path] = (st.st_mtime, st.st_size)
            except OSError:
                self._module_mtimes[abs_path] = (0.0, -1)
        else:
            self._module_mtimes[abs_path] = (0.0, -1)

        self._modules[abs_path] = plugin_cls
        pending = [abs_path]
        scanned: Set[str] = set()
        watch_root = os.path.dirname(abs_path)
        while pending:
            path = pending.pop()
            if path in scanned:
                continue
            scanned.add(path)
            for dependency in self.graph.scan_file(path, watch_root):
                try:
                    local = os.path.commonpath([watch_root, dependency]) == watch_root
                except ValueError:
                    local = False
                if local:
                    pending.append(dependency)

        def unregister() -> None:
            self._modules.pop(abs_path, None)
            self._module_mtimes.pop(abs_path, None)
            # Module refresh state is module-owned: disposing it must never
            # retire the config registration's serialization state for this path
            # (`index.ts:93-95,177-181`).
            state = self._module_refreshes.pop(abs_path, None)
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
        self._closing = True
        if self._cancel_ready is not None:
            self._cancel_ready()
            self._cancel_ready = None
        self._running = False
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        if self._poll_task is not None:
            await asyncio.gather(self._poll_task, return_exceptions=True)
        running_tasks = [s.running for s in self._config_refreshes.values()
                         if s and s.running and not s.running.done()]
        running_tasks.extend([s.running for s in self._module_refreshes.values()
                              if s and s.running and not s.running.done()])
        running_tasks.extend([t for t in self._refresh_tasks if not t.done()])
        if self._operations is not None and not self._operations.done():
            running_tasks.append(self._operations)
        if running_tasks and not self._executing.get():
            try:
                await asyncio.gather(*running_tasks, return_exceptions=True)
            except Exception:
                pass
        self._configs.clear()
        self._modules.clear()
        self._mtimes.clear()
        self._module_mtimes.clear()
        self._root_mtimes.clear()
        self._root_unlinks.clear()
        self._root_unlink_deadlines.clear()
        self._root_writes.clear()
        self._root_emitted.clear()
        self._config_refreshes.clear()
        self._module_refreshes.clear()
        self._config_paths.clear()
        self.modules.dispose()

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
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
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
