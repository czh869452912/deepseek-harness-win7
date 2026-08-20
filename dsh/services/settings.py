import json
import os
from typing import Any, Dict, Optional


class SettingsService:
    """
    Settings Service registered at `ctx.settings`.
    Manages persistent user and project settings (base_url, default model, timeouts, etc.).
    """

    def __init__(self, settings_file: Optional[str] = None):
        if settings_file:
            self.filepath = os.path.abspath(settings_file)
        else:
            home = os.path.expanduser("~")
            self.filepath = os.path.join(home, ".dsh", "settings.json")

        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                print(f"[SettingsService Warning] Failed to load settings from {self.filepath}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SettingsService Error] Failed to save settings to {self.filepath}: {e}")

    def get_setting(self, namespace: str, key: str, default: Any = None) -> Any:
        ns_dict = self._data.get(namespace, {})
        return ns_dict.get(key, default)

    def set_setting(self, namespace: str, key: str, value: Any, save_to_disk: bool = True) -> None:
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = value
        if save_to_disk:
            self.save()
