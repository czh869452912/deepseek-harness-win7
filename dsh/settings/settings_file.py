"""
File-backed settings provider (`ctx.settings`).
Aligned 1:1 with official `@deepseek-ai/dsh-settings` and `@deepseek-ai/dsh-settings-file`.
"""

import copy
import json
import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import yaml
from dsh.cordis.file_lock import FileLock

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin


class SettingsConflictError(ValueError):
    """Raised when a settings write expected revision does not match actual revision."""

    def __init__(self, ns: str, expected: int, actual: int):
        super().__init__(
            f'settings namespace "{ns}" changed since it was read (expected revision {expected}, now {actual})'
        )
        self.code = "SETTINGS_CONFLICT"
        self.ns = ns
        self.expected = expected
        self.actual = actual


def deep_equal_json(a: Any, b: Any) -> bool:
    """Deep structural equality over JSON-compatible values."""
    if a is b:
        return True
    if type(a) != type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(deep_equal_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(deep_equal_json(x, y) for x, y in zip(a, b))
    return a == b


def is_map_like(val: Any) -> bool:
    """Whether a value is a dictionary mapping for diffing purposes."""
    return isinstance(val, dict)


def patch_node(doc: dict, path: List[str], current: Any, next_val: Any) -> None:
    """
    Apply minimal edits to document dict, recursing through maps, so untouched nodes keep formatting.
    Non-map values replace wholesale when unequal.
    """
    if is_map_like(current) and is_map_like(next_val):
        target = doc
        for p in path:
            if not isinstance(target, dict):
                break
            if p not in target or not isinstance(target[p], dict):
                target[p] = {}
            target = target[p]
        if isinstance(target, dict):
            for key in list(current.keys()):
                if key not in next_val:
                    target.pop(key, None)
            for key, value in next_val.items():
                patch_node(doc, path + [key], current.get(key), value)
        return
    if not deep_equal_json(current, next_val):
        target = doc
        for p in path[:-1]:
            if p not in target or not isinstance(target[p], dict):
                target[p] = {}
            target = target[p]
        if path:
            target[path[-1]] = copy.deepcopy(next_val)


def apply_path_op(section: dict, op: dict) -> dict:
    """Apply one path op ({op: 'set'|'unset', path: list, value?: any}) to a section dict."""
    sec = copy.deepcopy(section) if isinstance(section, dict) else {}
    kind = op.get("op")
    path = op.get("path") or []
    if not path:
        if kind == "unset":
            return {}
        val = op.get("value")
        return dict(val) if isinstance(val, dict) else {}

    head = path[0]
    rest = path[1:]
    if not rest:
        if kind == "set":
            sec[head] = copy.deepcopy(op.get("value"))
        elif kind == "unset":
            sec.pop(head, None)
        return sec

    child = sec.get(head)
    if not isinstance(child, dict):
        if kind == "unset":
            return sec
        child = {}
    sec[head] = apply_path_op(child, {"op": kind, "path": rest, "value": op.get("value")})
    return sec


class SettingsWatcher:
    def __init__(self, callback: Callable):
        self.callback = callback
        self.active = True


class SettingsScope:
    """Owner-facing handle for one registered namespace."""

    def __init__(self, service: "SettingsService", ns: str):
        self.service = service
        self.ns = ns

    def get(self) -> Any:
        return self.service.get(self.ns)

    def watch(self, callback: Callable) -> Callable[[], None]:
        return self.service.watch(self.ns, callback)

    def update(self, patch: dict, expected_revision: Optional[int] = None) -> None:
        self.service.update(self.ns, patch, expected_revision=expected_revision)

    def replace(self, section: dict, expected_revision: Optional[int] = None) -> None:
        self.service.replace(self.ns, section, expected_revision=expected_revision)

    def mutate(self, ops: List[dict], expected_revision: Optional[int] = None) -> None:
        self.service.mutate(self.ns, ops, expected_revision=expected_revision)


class SettingsRegistration:
    def __init__(
        self,
        ns: str,
        schema: Any = None,
        base: Any = None,
        applies: str = "live",
        validate: Optional[Callable] = None,
    ):
        self.ns = ns
        self.schema = schema
        self.base = base
        self.applies = applies
        self.validate = validate
        self.resolved: Any = None
        self.revision: int = 0
        self.watchers: Set[SettingsWatcher] = set()


class SettingsService:
    """
    Settings Service registered at `ctx.settings`.
    1:1 with reference `packages/settings/settings-file/src/index.ts` + `packages/settings/settings/src`.
    """

    def __init__(
        self,
        ctx: Optional[Any] = None,
        settings_file: Optional[str] = None,
        watch: bool = False,
        debounce_ms: int = 100,
    ):
        self.ctx = ctx
        self._data: Dict[str, Any] = {}
        self._format: str = "yaml"
        self._revision: int = 1
        self._revisions: Dict[str, int] = {}
        self.writable: bool = True
        self._registrations: Dict[str, SettingsRegistration] = {}
        self._text: Optional[str] = None
        self._closed: bool = False
        self._watch: bool = watch
        self._debounce_ms: int = debounce_ms
        self._thread: Optional[threading.Thread] = None

        if settings_file:
            self.filepath = os.path.abspath(settings_file)
        else:
            home_dir = resolve_dsh_home()
            yaml_path = os.path.join(home_dir, "settings.yaml")
            yml_path = os.path.join(home_dir, "settings.yml")
            json_path = os.path.join(home_dir, "settings.json")
            if os.path.exists(yaml_path):
                self.filepath = yaml_path
            elif os.path.exists(yml_path):
                self.filepath = yml_path
            elif os.path.exists(json_path):
                self.filepath = json_path
            else:
                self.filepath = yaml_path

        if self.filepath.endswith(".json"):
            self._format = "json"
        else:
            self._format = "yaml"

        self.lock_path = self.filepath + ".lock"
        self._lock = threading.RLock()

        # Cold-start file creation when absent
        self.prepare_document()

        self.load()

        if self._watch and not self._closed:
            self._start_watcher()

    def prepare_document(self) -> str:
        """
        Materialize an absent owner-only document with a valid default map (1:1 with TS prepareDocument).
        """
        with self._lock:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            if not os.path.exists(self.filepath):
                lock = FileLock(self.lock_path, timeout=5)
                try:
                    with lock:
                        if not os.path.exists(self.filepath):
                            with open(self.filepath, "w", encoding="utf-8") as f:
                                if self._format == "json":
                                    f.write("{}\n")
                                else:
                                    f.write("# DeepSeek Harness Settings\n{}\n")
                            self._text = "{}"
                except Exception:
                    pass
        return self.filepath

    def _start_watcher(self) -> None:
        def _watch_loop():
            last_mtime = 0.0
            last_size = -1
            while not self._closed:
                try:
                    if os.path.exists(self.filepath):
                        st = os.stat(self.filepath)
                        mtime = st.st_mtime
                        size = st.st_size
                        if (mtime != last_mtime or size != last_size) and last_mtime != 0.0:
                            last_mtime = mtime
                            last_size = size
                            self.refresh()
                        else:
                            last_mtime = mtime
                            last_size = size
                except Exception:
                    pass
                time.sleep(max(0.05, self._debounce_ms / 1000.0))

        self._thread = threading.Thread(target=_watch_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True

    def parse(self, text: str) -> Dict[str, Any]:
        """Parse text into raw sections dict, failing on a non-map root."""
        if not text.strip():
            return {}
        try:
            if self._format == "json":
                root = json.loads(text)
            else:
                root = yaml.safe_load(text)
        except Exception as e:
            raise ValueError(f"settings-file: invalid document at {self.filepath}: {e}")
        if root is None:
            return {}
        if not isinstance(root, dict):
            raise TypeError(f"settings-file: {self.filepath} must be a map of namespace sections")
        return dict(root)

    def _load_unlocked(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                text = f.read()
            self._text = text
            self._data = self.parse(text)
        else:
            self._data = {}
            self._text = ""
        for ns in self._data.keys():
            if ns != "_meta" and ns not in self._revisions:
                self._revisions[ns] = 1
        return dict(self._data)

    def load(self) -> Dict[str, Any]:
        """Read document from disk under lock."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            try:
                with lock:
                    return self._load_unlocked()
            except Exception as e:
                self._log("warn", f"Failed to load settings from {self.filepath}: {e}")
                self._data = {}
                return {}

    def _reconcile_from_disk_unlocked(self) -> None:
        if self._closed:
            return
        if not os.path.exists(self.filepath):
            if self._text is not None:
                self._text = None
                self.publish({})
            return
        with open(self.filepath, "r", encoding="utf-8") as f:
            text = f.read()
        if text == self._text:
            return
        doc = self.parse(text)
        self._text = text
        self.publish(doc)

    def reconcile_from_disk(self) -> None:
        """Compare on-disk text against cache and publish any difference."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self._reconcile_from_disk_unlocked()

    def refresh(self) -> None:
        """Hot-reload refresh wrapper."""
        if self._closed:
            return
        try:
            self.reconcile_from_disk()
        except Exception as e:
            self._log("warn", f"settings-file: reload failed at {self.filepath}; keeping last good document: {e}")

    def publish(self, doc: Dict[str, Any], source: str = "provider") -> None:
        """Publish updated raw document into registered namespaces and notify subscribers."""
        before_sections: Dict[str, Any] = {}
        for ns in self._registrations.keys():
            before_sections[ns] = copy.deepcopy(self._data.get(ns))

        self._data = copy.deepcopy(doc)

        for ns, reg in list(self._registrations.items()):
            after_section = self._data.get(ns)
            if not isinstance(after_section, dict):
                after_section = None

            before_sec = before_sections.get(ns)
            if not isinstance(before_sec, dict):
                before_sec = None

            if not deep_equal_json(before_sec, after_section):
                reg.revision += 1
                self._revisions[ns] = reg.revision
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("settings/document-updated", ns, reg.revision)
                    except Exception:
                        pass

            section = after_section or {}
            merged = copy.deepcopy(reg.base) if isinstance(reg.base, dict) else {}
            merged.update(section)

            if reg.validate:
                try:
                    reg.validate(merged)
                except Exception as e:
                    self._log("warn", f'settings: keeping last good "{ns}" after invalid stored section: {e}')
                    continue

            prev_val = reg.resolved
            next_val = merged
            if not deep_equal_json(prev_val, next_val):
                reg.resolved = copy.deepcopy(next_val)
                for watcher in list(reg.watchers):
                    if watcher.active:
                        try:
                            watcher.callback(next_val, prev_val)
                        except Exception as e:
                            self._log("warn", f"settings watcher for {ns} failed: {e}")
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("settings/updated", ns, next_val, prev_val, source)
                    except Exception:
                        pass

    def register(
        self,
        ns: str,
        schema: Any = None,
        base: Any = None,
        applies: str = "live",
        validate: Optional[Callable] = None,
    ) -> SettingsScope:
        """Register a namespace schema and return its owner scope."""
        if ns in self._registrations:
            raise ValueError(f'settings namespace "{ns}" is already registered')

        reg = SettingsRegistration(ns=ns, schema=schema, base=base, applies=applies, validate=validate)
        section = self._data.get(ns, {})
        if not isinstance(section, dict):
            section = {}
        merged = copy.deepcopy(base) if isinstance(base, dict) else {}
        merged.update(section)
        if validate:
            validate(merged)
        reg.resolved = copy.deepcopy(merged)
        reg.revision = self._revisions.get(ns, 1)
        self._registrations[ns] = reg

        if self.ctx and hasattr(self.ctx, "effect"):
            try:
                def _effect():
                    yield lambda: self._registrations.pop(ns, None)
                self.ctx.effect(_effect, f"settings.register({ns})")
            except Exception:
                pass

        return SettingsScope(self, ns)

    def describe(self, options: Optional[dict] = None) -> List[Dict[str, Any]]:
        """Describe every registered namespace for configuration surfaces."""
        res = []
        redact = bool(options and options.get("redactSecrets"))
        for ns, reg in self._registrations.items():
            user = self._data.get(ns) if ns in self._data and isinstance(self._data[ns], dict) else None
            val = copy.deepcopy(reg.resolved)
            base = copy.deepcopy(reg.base) if reg.base is not None else None
            secrets = []
            if redact and isinstance(val, dict) and ("apiKey" in val or "api_key" in val):
                if "apiKey" in val:
                    secrets.append({"path": ["apiKey"], "set": bool(val["apiKey"])})
                    val["apiKey"] = "******" if val["apiKey"] else ""
                if "api_key" in val:
                    secrets.append({"path": ["api_key"], "set": bool(val["api_key"])})
                    val["api_key"] = "******" if val["api_key"] else ""
            desc = {
                "ns": ns,
                "schema": reg.schema,
                "value": val,
                "revision": reg.revision,
                "applies": reg.applies,
            }
            if base is not None:
                desc["base"] = base
            if user is not None:
                desc["user"] = copy.deepcopy(user)
            if redact and secrets:
                desc["secrets"] = secrets
            res.append(desc)
        return res

    def get(self, ns: str) -> Any:
        reg = self._registrations.get(ns)
        return reg.resolved if reg else self._data.get(ns)

    def watch(self, ns: str, callback: Callable) -> Callable[[], None]:
        reg = self._registrations.get(ns)
        if not reg:
            reg = SettingsRegistration(ns=ns)
            self._registrations[ns] = reg
        watcher = SettingsWatcher(callback)
        reg.watchers.add(watcher)

        def dispose():
            watcher.active = False
            reg.watchers.discard(watcher)

        return dispose

    def _check_conflict(self, ns: str, expected_revision: Optional[int]) -> None:
        if expected_revision is None:
            return
        actual = self.get_revision(ns)
        if int(expected_revision) != int(actual):
            raise SettingsConflictError(ns, expected=int(expected_revision), actual=int(actual))

    def update(self, ns: str, patch: dict, expected_revision: Optional[int] = None) -> None:
        """Merge patch into namespace's user layer and persist to disk."""
        if not isinstance(patch, dict):
            raise TypeError(f'settings update for "{ns}" must be a plain object')
        self._check_conflict(ns, expected_revision)
        current = copy.deepcopy(self._data.get(ns, {})) if isinstance(self._data.get(ns), dict) else {}
        merged = copy.deepcopy(current)
        merged.update(patch)

        reg = self._registrations.get(ns)
        if reg and reg.validate:
            check_val = copy.deepcopy(reg.base) if isinstance(reg.base, dict) else {}
            check_val.update(merged)
            reg.validate(check_val)

        self._persist_section(ns, merged)

    def replace(self, ns: str, section: dict, expected_revision: Optional[int] = None) -> None:
        """Replace namespace's user section wholesale and persist to disk."""
        if not isinstance(section, dict):
            raise TypeError(f'settings replace for "{ns}" must be a plain object')
        self._check_conflict(ns, expected_revision)
        next_sec = copy.deepcopy(section)

        reg = self._registrations.get(ns)
        if reg and reg.validate:
            check_val = copy.deepcopy(reg.base) if isinstance(reg.base, dict) else {}
            check_val.update(next_sec)
            reg.validate(check_val)

        self._persist_section(ns, next_sec)

    def mutate(self, ns: str, ops: List[dict], expected_revision: Optional[int] = None) -> None:
        """Apply path ops to namespace's user section and persist to disk."""
        if not isinstance(ops, list):
            raise TypeError(f'settings mutate for "{ns}" must be a list of path ops')
        self._check_conflict(ns, expected_revision)
        current = copy.deepcopy(self._data.get(ns, {})) if isinstance(self._data.get(ns), dict) else {}
        next_sec = current
        for op in ops:
            next_sec = apply_path_op(next_sec, op)

        reg = self._registrations.get(ns)
        if reg and reg.validate:
            check_val = copy.deepcopy(reg.base) if isinstance(reg.base, dict) else {}
            check_val.update(next_sec)
            reg.validate(check_val)

        self._persist_section(ns, next_sec)

    def _persist_section(self, ns: str, section: dict) -> None:
        """Persist section write to disk under file lock and notify subscribers."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self._reconcile_from_disk_unlocked()
                doc = copy.deepcopy(self._data)
                patch_node(doc, [ns], doc.get(ns), section)

                os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
                dir_name = os.path.dirname(self.filepath) or "."
                fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="settings_", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        if self._format == "json":
                            output = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
                        else:
                            output = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        f.write(output)
                    os.replace(tmp, self.filepath)
                    self._text = output
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass

                self.publish(doc, source="update")

    def save(self) -> None:
        """Save current _data state to disk."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
                dir_name = os.path.dirname(self.filepath) or "."
                fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="settings_", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        if self._format == "json":
                            output = json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"
                        else:
                            output = yaml.dump(self._data, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        f.write(output)
                    os.replace(tmp, self.filepath)
                    self._text = output
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("settings/document-updated", {"path": self.filepath})
                        self.ctx.emit("settings/updated")
                    except Exception:
                        pass

    def get_revision(self, ns: str) -> int:
        reg = self._registrations.get(ns)
        if reg:
            return reg.revision
        return int(self._revisions.get(ns, 1))

    def bump_revision(self, ns: str) -> int:
        reg = self._registrations.get(ns)
        if reg:
            reg.revision += 1
            cur = reg.revision
        else:
            cur = self._revisions.get(ns, 1) + 1
        self._revisions[ns] = cur
        self._revision = max(self._revision + 1, cur)
        return cur

    def get_section(self, namespace: str) -> Dict[str, Any]:
        v = self.get(namespace)
        if isinstance(v, dict):
            return dict(v)
        v_raw = self._data.get(namespace, {})
        if isinstance(v_raw, dict):
            return dict(v_raw)
        return {}

    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        ns_dict = self.get_section(namespace)
        return ns_dict.get(key, default)

    def set_setting(self, namespace: str, key: str, value: Any, save_to_disk: bool = True) -> None:
        if save_to_disk:
            self.update(namespace, {key: value})
        else:
            if namespace not in self._data or not isinstance(self._data[namespace], dict):
                self._data[namespace] = {}
            self._data[namespace][key] = value
            self.bump_revision(namespace)
            if self.ctx and hasattr(self.ctx, "emit"):
                try:
                    self.ctx.emit("settings/updated")
                except Exception:
                    pass

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self.ctx, "logger", None) if self.ctx else None
        if logger is not None:
            try:
                getattr(logger, level)(message)
                return
            except Exception:
                pass


class SettingsFilePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-settings-file`: Mounts user and project settings store (`ctx.settings`).
    """

    id = "settings-file"
    name = "@deepseek-ai/dsh-settings-file"

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        settings_file = cfg.get("settingsFile", cfg.get("path"))
        watch = cfg.get("watch", False)
        debounce_ms = cfg.get("debounceMs", 100)
        settings_service = SettingsService(
            ctx=ctx,
            settings_file=settings_file,
            watch=watch,
            debounce_ms=debounce_ms,
        )

        initial_settings = cfg.get("settings", {})
        for ns, kv in initial_settings.items():
            if ns == "_meta":
                continue
            if isinstance(kv, dict):
                for k, v in kv.items():
                    settings_service.set_setting(ns, k, v, save_to_disk=False)

        ctx.set_service("settings", settings_service)
        try:
            ctx.emit("settings/ready", settings_service)
        except Exception:
            pass
