"""
Agent Preset Domain Handler (`@deepseek-ai/dsh-apiproxy/api/agent-presets`).
Handles `agentPreset.list`, `agentPreset.select`, `agentPreset.read`, `agentPreset.copy`, `agentPreset.openDocument`, `agentPreset.remove`.
Aligned 1:1 with reference `api/agent-presets.ts`.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.host.apiproxy.native_path_opener import open_native_path


class AgentPresetsDomainHandler:
    """Handler for agentPreset.* RPC methods."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    async def list_presets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        presets = [
            {
                "id": "minimal",
                "trust": "system",
                "isDefault": False,
                "name": "极简模式 (Minimal)",
                "description": "零额外开销，双工具",
            },
            {
                "id": "standard",
                "trust": "system",
                "isDefault": True,
                "name": "标准模式 (Standard)",
                "description": "通用软件工程 Agent，全套工程工具",
            },
            {
                "id": "creative",
                "trust": "system",
                "isDefault": False,
                "name": "创造模式 (Creative)",
                "description": "Cordis 双平面架构自省与扩展",
            },
        ]
        return {
            "presets": presets,
            "authorable": True,
            "hasDocument": True,
        }

    async def select_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId") or payload.get("preset", "standard")
        session_id = payload.get("sessionId")
        sessions_svc = self.ctx.get("sessions")
        if sessions_svc and session_id and session_id in sessions_svc._sessions:
            sessions_svc._sessions[session_id].header.agent_preset = preset_id
        return {"agentPreset": preset_id}

    async def read_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId", "standard")
        preset_path = os.path.join(os.getcwd(), "dsh", "presets", f"{preset_id}.yaml")
        content = ""
        if os.path.isfile(preset_path):
            with open(preset_path, "r", encoding="utf-8") as f:
                content = f.read()
        return {
            "agentPreset": preset_id,
            "trust": "system",
            "content": content,
            "name": f"{preset_id.capitalize()} Preset",
            "description": f"Configuration preset for {preset_id}",
        }

    async def copy_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        src_id = payload.get("from") or payload.get("sourcePresetId", "standard")
        target_id = payload.get("agentPreset") or payload.get("newPresetId", f"custom-{src_id}")
        return {"agentPreset": target_id}

    async def open_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId", "standard")
        preset_path = os.path.join(os.getcwd(), "dsh", "presets", f"{preset_id}.yaml")
        opened = open_native_path(preset_path)
        if opened:
            return {"opened": True}
        return {"opened": False, "path": preset_path.replace("\\", "/")}

    async def remove_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}
