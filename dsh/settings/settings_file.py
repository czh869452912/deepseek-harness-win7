import json
import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin


class SettingsService:
    """
    Settings Service registered at `ctx.settings`.
    Manages persistent user and project settings (base_url, default model, timeouts, etc.).
    Supports YAML ($DSH_HOME/settings.yaml) and JSON ($DSH_HOME/settings.json).
    """

    def __init__(self, ctx: Optional[Any] = None, settings_file: Optional[str] = None):
        self.ctx = ctx
        self._data: Dict[str, Any] = {}
        self._format: str = "yaml"
        self._revision: int = 1
        self.writable: bool = True

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
            except Exception as e:
                if self.ctx and hasattr(self.ctx, "logger") and self.ctx.logger:
                    self.ctx.logger.warn("Failed to load settings from %s: %s", self.filepath, str(e))
                else:
                    print(f"[SettingsService Warning] Failed to load settings from {self.filepath}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                if self._format == "json":
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                else:
                    yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            if self.ctx and hasattr(self.ctx, "logger") and self.ctx.logger:
                self.ctx.logger.error("Failed to save settings to %s: %s", self.filepath, str(e))
            else:
                print(f"[SettingsService Error] Failed to save settings to {self.filepath}: {e}")

    def get_section(self, namespace: str) -> Dict[str, Any]:
        return self._data.get(namespace, {})

    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        ns_dict = self._data.get(namespace, {})
        if isinstance(ns_dict, dict):
            return ns_dict.get(key, default)
        return default

    def set_setting(self, namespace: str, key: str, value: Any, save_to_disk: bool = True) -> None:
        if namespace not in self._data or not isinstance(self._data[namespace], dict):
            self._data[namespace] = {}
        self._data[namespace][key] = value
        if save_to_disk:
            self.save()


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
            if isinstance(kv, dict):
                for k, v in kv.items():
                    settings_service.set_setting(ns, k, v, save_to_disk=False)

        ctx.set_service("settings", settings_service)
