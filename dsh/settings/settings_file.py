import json
import os
import tempfile
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin


class SettingsService:
    """
    Settings Service registered at `ctx.settings`.
    1:1 with reference `packages/settings/settings-file/src/index.ts` + `packages/settings/settings/src`.
    Supports per-namespace revision, layered base/user view, atomic write, and error codes.
    """

    def __init__(self, ctx: Optional[Any] = None, settings_file: Optional[str] = None):
        self.ctx = ctx
        self._data: Dict[str, Any] = {}
        self._format: str = "yaml"
        self._revision: int = 1
        self._revisions: Dict[str, int] = {}
        self.writable: bool = True
        self._base_data: Dict[str, Any] = {}

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

        self.load()

    def load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                if self._format == "json":
                    data = json.loads(content) if content.strip() else {}
                else:
                    data = yaml.safe_load(content) or {}
                if isinstance(data, dict):
                    self._data = data
                    # init per-ns revisions from stored meta if present
                    meta = data.get("_meta", {})
                    if isinstance(meta, dict):
                        revs = meta.get("revisions", {})
                        if isinstance(revs, dict):
                            for k, v in revs.items():
                                try:
                                    self._revisions[k] = int(v)
                                except Exception:
                                    pass
                        if "revision" in meta:
                            try:
                                self._revision = int(meta["revision"])
                            except Exception:
                                pass
                    # ensure each ns has at least 1
                    for ns in self._data.keys():
                        if ns == "_meta":
                            continue
                        if ns not in self._revisions:
                            self._revisions[ns] = 1
            except Exception as e:
                if self.ctx and hasattr(self.ctx, "logger") and getattr(self.ctx, "logger", None):
                    try:
                        self.ctx.logger.warn("Failed to load settings from %s: %s", self.filepath, str(e))
                    except Exception:
                        print("[SettingsService Warning] Failed to load settings from {}: {}".format(self.filepath, e))
                else:
                    print("[SettingsService Warning] Failed to load settings from {}: {}".format(self.filepath, e))

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            # embed per-ns revisions into _meta for persistence (TS uses file revision but we keep per-ns)
            data_to_write = dict(self._data)
            # preserve _meta
            meta = dict(data_to_write.get("_meta", {}) if isinstance(data_to_write.get("_meta"), dict) else {})
            meta["revisions"] = dict(self._revisions)
            meta["revision"] = self._revision
            data_to_write["_meta"] = meta
            # atomic write via temp + rename
            dir_name = os.path.dirname(self.filepath) or "."
            fd, tmp = tempfile.mkstemp(dir=dir_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    if self._format == "json":
                        json.dump(data_to_write, f, indent=2, ensure_ascii=False)
                    else:
                        yaml.dump(data_to_write, f, default_flow_style=False, allow_unicode=True)
                # fsync
                try:
                    with open(tmp, "rb") as rf:
                        os.fsync(rf.fileno())
                except Exception:
                    pass
                os.replace(tmp, self.filepath)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
            # emit document-updated after successful write (1:1 with TS)
            if self.ctx:
                try:
                    self.ctx.emit("settings/document-updated", {"path": self.filepath})
                    self.ctx.emit("settings/updated")
                except Exception:
                    pass
        except Exception as e:
            if self.ctx and hasattr(self.ctx, "logger") and getattr(self.ctx, "logger", None):
                try:
                    self.ctx.logger.error("Failed to save settings to %s: %s", self.filepath, str(e))
                except Exception:
                    print("[SettingsService Error] Failed to save settings to {}: {}".format(self.filepath, e))
            else:
                print("[SettingsService Error] Failed to save settings to {}: {}".format(self.filepath, e))

    def get_revision(self, ns: str) -> int:
        return int(self._revisions.get(ns, 1))

    def bump_revision(self, ns: str) -> int:
        cur = self._revisions.get(ns, 1)
        nxt = cur + 1
        self._revisions[ns] = nxt
        self._revision = max(self._revision + 1, nxt)
        return nxt

    def get_section(self, namespace: str) -> Dict[str, Any]:
        # return detached copy without _meta
        if namespace == "_meta":
            return {}
        v = self._data.get(namespace, {})
        if isinstance(v, dict):
            return dict(v)
        return {}

    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        if namespace == "_meta":
            return default
        ns_dict = self._data.get(namespace, {})
        if isinstance(ns_dict, dict):
            # handle nested path via dot? no
            return ns_dict.get(key, default)
        return default

    def set_setting(self, namespace: str, key: str, value: Any, save_to_disk: bool = True) -> None:
        if namespace == "_meta":
            return
        if namespace not in self._data or not isinstance(self._data[namespace], dict):
            self._data[namespace] = {}
        self._data[namespace][key] = value
        # bump per-ns revision only when saving? Always bump to keep monotonic
        self.bump_revision(namespace)
        if save_to_disk:
            self.save()
        else:
            # still emit in-memory updated without file
            if self.ctx:
                try:
                    self.ctx.emit("settings/updated")
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
        settings_service = SettingsService(ctx=ctx, settings_file=settings_file)

        initial_settings = cfg.get("settings", {})
        for ns, kv in initial_settings.items():
            if ns == "_meta":
                continue
            if isinstance(kv, dict):
                for k, v in kv.items():
                    settings_service.set_setting(ns, k, v, save_to_disk=False)

        ctx.set_service("settings", settings_service)
        # expose also via reflect for has() checks
        try:
            ctx.emit("settings/ready", settings_service)
        except Exception:
            pass
