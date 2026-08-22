"""
File-backed settings provider (`ctx.settings`).
Aligned 1:1 with reference @deepseek-ai/dsh-settings-file.
"""

import copy
import json
import os
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.file_lock import FileLock
from dsh.cordis.plugin import Plugin
from dsh.settings.provider import (
    SettingsConflictError,
    SettingsDescriptor,
    SettingsProvider,
    SettingsRegistration,
    SettingsScope,
    deep_equal_json,
    is_plain_object,
    merge_layers,
)

FORMATS = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
}


class ResolvedSpec:

    def __init__(self, filename: str, format_type: str, watch: bool, debounce_ms: int):
        self.filename = filename
        self.format = format_type
        self.watch = watch
        self.debounce_ms = debounce_ms


def resolve_spec(config: Union[dict, Any]) -> ResolvedSpec:
    """
    Resolve the runtime spec from plugin config: an explicit `path` wins,
    otherwise the document lives at `<harness home>/settings.yaml`.
    """
    cfg = config if isinstance(config, dict) else (getattr(config, "__dict__", {}) or {})
    raw_path = cfg.get("path") or cfg.get("settingsFile")
    dsh_home = cfg.get("dshHome") or cfg.get("dsh_home")

    if raw_path:
        filename = os.path.abspath(raw_path)
    else:
        home_dir = resolve_dsh_home(dsh_home)
        yaml_path = os.path.join(home_dir, "settings.yaml")
        yml_path = os.path.join(home_dir, "settings.yml")
        json_path = os.path.join(home_dir, "settings.json")
        if os.path.exists(yaml_path):
            filename = yaml_path
        elif os.path.exists(yml_path):
            filename = yml_path
        elif os.path.exists(json_path):
            filename = json_path
        else:
            filename = yaml_path

    _, ext = os.path.splitext(filename)
    fmt = FORMATS.get(ext.lower())
    if fmt is None:
        raise ValueError(f'settings-file: extension "{ext}" is not supported (use .yaml, .yml, or .json)')

    watch = bool(cfg.get("watch", True))
    debounce_ms = int(cfg.get("debounceMs", cfg.get("debounce_ms", 100)))

    return ResolvedSpec(
        filename=filename,
        format_type=fmt,
        watch=watch,
        debounce_ms=debounce_ms,
    )


def is_map_like(val: Any) -> bool:
    return isinstance(val, dict)


def patch_node(doc: dict, path: List[str], current: Any, next_val: Any) -> None:
    """
    Apply minimal edits to document dict, recursing through maps, so untouched nodes keep formatting.
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


class FileSettingsProvider(SettingsProvider):
    """
    File-backed settings provider (`settings.yaml`/`.json`).
    1:1 with reference @deepseek-ai/dsh-settings-file.
    """

    def __init__(
        self,
        ctx: Optional[Any] = None,
        config: Optional[Union[dict, str]] = None,
        settings_file: Optional[str] = None,
        watch: Optional[bool] = None,
        debounce_ms: Optional[int] = None,
    ):
        super().__init__(ctx)

        if isinstance(config, str):
            cfg_dict: Dict[str, Any] = {"path": config}
        elif isinstance(config, dict):
            cfg_dict = dict(config)
        else:
            cfg_dict = {}

        if settings_file:
            cfg_dict["path"] = settings_file
        if watch is not None:
            cfg_dict["watch"] = watch
        if debounce_ms is not None:
            cfg_dict["debounceMs"] = debounce_ms

        self.config = cfg_dict
        self.spec = resolve_spec(cfg_dict)
        self.filepath = self.spec.filename
        self.lock_path = self.spec.filename + ".lock"
        self._lock = threading.RLock()
        self._text: Optional[str] = None
        self._closed: bool = False
        self._thread: Optional[threading.Thread] = None

        self.prepare_document()
        self.load()

        if self.spec.watch and not self._closed:
            self._start_watcher()

    @property
    def writable(self) -> bool:
        return True

    @property
    def document_path(self) -> str:
        return self.spec.filename

    @property
    def _data(self) -> Dict[str, Any]:
        return self._document

    @_data.setter
    def _data(self, val: Dict[str, Any]) -> None:
        self._document = val

    @property
    def _revisions(self) -> Dict[str, int]:
        return {ns: reg.revision for ns, reg in self._registrations.items()}

    def prepare_document(self) -> str:
        """Materialize an absent owner-only document."""
        with self._lock:
            dir_name = os.path.dirname(self.spec.filename) or "."
            os.makedirs(dir_name, exist_ok=True)
            if not os.path.exists(self.spec.filename):
                lock = FileLock(self.lock_path, timeout=5)
                try:
                    with lock:
                        if not os.path.exists(self.spec.filename):
                            with open(self.spec.filename, "w", encoding="utf-8") as f:
                                if self.spec.format == "json":
                                    f.write("{}\n")
                                else:
                                    f.write("# DeepSeek Harness Settings\n{}\n")
                            self._text = "{}"
                            if not self._stopped:
                                self.publish({})
                except Exception:
                    pass
        return self.spec.filename

    def load(self) -> Dict[str, Any]:
        """Load user document and optional project (.dsh/settings.yaml) document."""
        with self._lock:
            user_doc = self._load_single_file(self.spec.filename)

            # Check for project settings layer in current working directory (.dsh/settings.yaml)
            project_doc = {}
            cwd_project_yaml = os.path.abspath(os.path.join(os.getcwd(), ".dsh", "settings.yaml"))
            cwd_project_yml = os.path.abspath(os.path.join(os.getcwd(), ".dsh", "settings.yml"))
            target_proj = None
            if os.path.exists(cwd_project_yaml) and os.path.abspath(cwd_project_yaml) != os.path.abspath(self.spec.filename):
                target_proj = cwd_project_yaml
            elif os.path.exists(cwd_project_yml) and os.path.abspath(cwd_project_yml) != os.path.abspath(self.spec.filename):
                target_proj = cwd_project_yml

            if target_proj:
                try:
                    project_doc = self._load_single_file(target_proj)
                except Exception:
                    project_doc = {}

            merged_doc = merge_layers(user_doc, project_doc) if project_doc else user_doc
            self._document = merged_doc
            return dict(self._document)

    def _load_single_file(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            if path == self.spec.filename:
                self._text = text
            return self.parse(text)
        except Exception as e:
            self._log("warn", f"Failed to load settings from {path}: {e}")
            return {}

    def parse(self, text: str) -> Dict[str, Any]:
        """Parse text into raw sections dict, failing on non-map root."""
        if not text or not text.strip():
            return {}
        try:
            if self.spec.format == "json":
                root = json.loads(text)
            else:
                root = yaml.safe_load(text)
        except Exception as e:
            raise ValueError(f"settings-file: invalid document at {self.spec.filename}: {e}")

        if root is None:
            return {}
        if not is_plain_object(root):
            raise TypeError(f"settings-file: {self.spec.filename} must be a map of namespace sections")
        return dict(root)

    def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        """Persist one section to disk under writer lock."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                self.reconcile_from_disk()
                doc = copy.deepcopy(self._document)
                patch_node(doc, [ns], doc.get(ns), section)

                dir_name = os.path.dirname(self.spec.filename) or "."
                os.makedirs(dir_name, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="settings_", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        if self.spec.format == "json":
                            output = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
                        else:
                            output = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        f.write(output)
                    os.replace(tmp, self.spec.filename)
                    self._text = output
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass

    def reconcile_from_disk(self) -> None:
        """Compare on-disk text against cache and publish any difference."""
        if self._closed or self._stopped:
            return
        if not os.path.exists(self.spec.filename):
            if self._text is not None:
                self._text = None
                self.publish({})
            return
        with open(self.spec.filename, "r", encoding="utf-8") as f:
            text = f.read()
        if text == self._text:
            return
        doc = self.parse(text)
        self._text = text
        self.publish(doc, source="provider")

    def refresh(self) -> None:
        """Hot-reload refresh wrapper."""
        if self._closed or self._stopped:
            return
        try:
            self.reconcile_from_disk()
        except Exception as e:
            self._log("warn", f"settings-file: reload failed at {self.spec.filename}; keeping last good document: {e}")

    def _start_watcher(self) -> None:
        def _watch_loop():
            last_mtime = 0.0
            last_size = -1
            while not self._closed and not self._stopped:
                try:
                    if os.path.exists(self.spec.filename):
                        st = os.stat(self.spec.filename)
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
                time.sleep(max(0.05, self.spec.debounce_ms / 1000.0))

        self._thread = threading.Thread(target=_watch_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True
        self._stopped = True

    # Legacy helper methods for backward compatibility
    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        sec = self.get(namespace)
        if is_plain_object(sec):
            return sec.get(key, default)
        raw_sec = self._document.get(namespace)
        if is_plain_object(raw_sec):
            return raw_sec.get(key, default)
        return default

    def set_setting(self, namespace: str, key: str, value: Any, save_to_disk: bool = True) -> None:
        if save_to_disk and self._registrations.get(namespace):
            self.update(namespace, {key: value})
        else:
            if namespace not in self._document or not is_plain_object(self._document[namespace]):
                self._document[namespace] = {}
            self._document[namespace][key] = value
            reg = self._registrations.get(namespace)
            if reg:
                reg.revision += 1
                self.commit(reg, copy.deepcopy(self._document[namespace]), source="update")
            elif save_to_disk:
                self._persist_section(namespace, self._document[namespace])

    def get_revision(self, ns: str) -> int:
        reg = self._registrations.get(ns)
        return reg.revision if reg else 1

    def bump_revision(self, ns: Union[str, SettingsRegistration], before: Any = None, after: Any = None) -> int:
        if isinstance(ns, SettingsRegistration):
            super().bump_revision(ns, before, after)
            return ns.revision
        reg = self._registrations.get(ns)
        if reg:
            reg.revision += 1
            self._emit_document_updated(ns, reg.revision)
            return reg.revision
        return 1

    def get_section(self, namespace: str) -> Dict[str, Any]:
        val = self.get(namespace)
        if is_plain_object(val):
            return dict(val)
        raw = self._document.get(namespace, {})
        return dict(raw) if is_plain_object(raw) else {}

    def save(self) -> None:
        """Save current _document state to disk."""
        with self._lock:
            lock = FileLock(self.lock_path, timeout=5)
            with lock:
                dir_name = os.path.dirname(self.spec.filename) or "."
                os.makedirs(dir_name, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="settings_", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        if self.spec.format == "json":
                            output = json.dumps(self._document, indent=2, ensure_ascii=False) + "\n"
                        else:
                            output = yaml.dump(self._document, default_flow_style=False, allow_unicode=True, sort_keys=False)
                        f.write(output)
                    os.replace(tmp, self.spec.filename)
                    self._text = output
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                self.publish(self._document, source="update")


# Alias for backward compatibility
SettingsService = FileSettingsProvider


class SettingsFilePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-settings-file`: Mounts user and project settings store (`ctx.settings`).
    """

    id = "settings-file"
    name = "@deepseek-ai/dsh-settings-file"

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        settings_service = FileSettingsProvider(ctx=ctx, config=cfg)

        initial_settings = cfg.get("settings", {})
        if is_plain_object(initial_settings):
            for ns, kv in initial_settings.items():
                if ns == "_meta" or not is_plain_object(kv):
                    continue
                for k, v in kv.items():
                    settings_service.set_setting(ns, k, v, save_to_disk=False)

        ctx.set_service("settings", settings_service)
        try:
            ctx.emit("settings/ready", settings_service)
        except Exception:
            pass
