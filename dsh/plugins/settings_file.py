from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.settings import SettingsService


class SettingsFilePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-settings-file`: Mounts user and project settings store (`ctx.settings`).
    """

    id = "settings-file"
    name = "@deepseek-ai/dsh-settings-file"

    def apply(self, ctx: Any) -> None:
        settings_file = self.config.get("settingsFile")
        settings_service = SettingsService(settings_file=settings_file)

        # Pre-seed initial settings from plugin config if present
        initial_settings = self.config.get("settings", {})
        for ns, kv in initial_settings.items():
            if isinstance(kv, dict):
                for k, v in kv.items():
                    settings_service.set_setting(ns, k, v, save_to_disk=False)

        ctx.set_service("settings", settings_service)
