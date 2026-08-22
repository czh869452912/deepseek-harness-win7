"""
Settings Domain Handler (`@deepseek-ai/dsh-apiproxy/api/settings`).
Handles all 5 settings RPC methods aligned 1:1 with reference `api/settings.ts`.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.host.apiproxy.native_path_opener import open_native_path


class SettingsDomainHandler:
    """Handler for settings.* RPC methods."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def describe_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        settings_svc = self.ctx.get("settings")
        llm = self.ctx.get("llm")
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or (llm and getattr(llm, "static_api_key", None)))
        llm_info = {
            "baseUrl": llm.resolve_base_url() if llm else "https://api.deepseek.com",
            "model": llm.resolve_model() if llm else "deepseek-chat",
            "hasKey": has_key,
        }
        general_info = {"theme": "dark", "locale": "zh-CN"}
        plugins_list = [
            {"id": "shell", "name": "Persistent Terminal Shell (pwsh/bash)", "active": True},
            {"id": "agent-loop", "name": "Cordis Agent Loop & Step Driver", "active": True},
            {"id": "compaction", "name": "Context Compaction & Summary Engine", "active": True},
            {"id": "fs-search", "name": "Filesystem Search (glob/grep)", "active": True},
            {"id": "web-search", "name": "DeepSeek / Tavily Web Search Engine", "active": True},
        ]
        namespaces = [
            {
                "ns": "llm",
                "schema": {},
                "value": llm_info,
                "secrets": [{"path": ["apiKey"], "set": has_key}],
                "applies": "live",
                "revision": 1,
            },
            {
                "ns": "general",
                "schema": {},
                "value": general_info,
                "secrets": [],
                "applies": "live",
                "revision": 1,
            },
        ]
        return {
            "llm": llm_info,
            "general": general_info,
            "plugins": plugins_list,
            "writable": True,
            "hasDocument": False,
            "namespaces": namespaces,
        }

    async def open_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open settings file in OS default editor (`settings.openDocument`)."""
        settings_path = os.path.join(os.getcwd(), "settings.yaml")
        if not os.path.isfile(settings_path):
            try:
                with open(settings_path, "w", encoding="utf-8") as f:
                    f.write("# DeepSeek Harness Settings\n")
            except Exception:
                pass
        opened = open_native_path(settings_path)
        return {"opened": opened, "path": settings_path.replace("\\", "/")}

    async def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm")
        if llm:
            if payload.get("baseUrl"):
                llm.static_base_url = payload["baseUrl"]
            if payload.get("apiKey"):
                llm.static_api_key = payload["apiKey"]
            if payload.get("model"):
                llm.static_model = payload["model"]
        settings_svc = self.ctx.get("settings")
        if settings_svc:
            if payload.get("baseUrl"):
                settings_svc.set_setting("llm", "base_url", payload["baseUrl"])
            if payload.get("model"):
                settings_svc.set_setting("llm", "model", payload["model"])
        return {"success": True, "saved": True}

    async def replace_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Replace full settings document (`settings.replace`)."""
        new_values = payload.get("values", {})
        return await self.update_settings(new_values)

    async def mutate_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Mutate specific settings namespace path (`settings.mutate`)."""
        updates = payload.get("updates", {})
        return await self.update_settings(updates)
