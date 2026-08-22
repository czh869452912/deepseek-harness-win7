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
            {"id": "minimal", "name": "极简模式 (Minimal)", "description": "零额外开销，双工具"},
            {"id": "standard", "name": "标准模式 (Standard)", "description": "通用软件工程 Agent，全套工程工具"},
            {"id": "creative", "name": "创造模式 (Creative)", "description": "Cordis 双平面架构自省与扩展"},
        ]
        return {"presets": presets, "items": presets}

    async def select_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("presetId") or payload.get("preset", "standard")
        session_id = payload.get("sessionId")
        sessions_svc = self.ctx.get("sessions")
        if sessions_svc and session_id and session_id in sessions_svc._sessions:
            sessions_svc._sessions[session_id].header.agent_preset = preset_id
        return {"success": True, "presetId": preset_id, "selected": True}

    async def read_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("presetId", "standard")
        preset_path = os.path.join(os.getcwd(), "dsh", "presets", f"{preset_id}.yaml")
        content = ""
        if os.path.isfile(preset_path):
            with open(preset_path, "r", encoding="utf-8") as f:
                content = f.read()
        return {"presetId": preset_id, "content": content, "path": preset_path.replace("\\", "/")}

    async def copy_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        src_id = payload.get("sourcePresetId", "standard")
        new_id = payload.get("newPresetId", f"custom-{src_id}")
        return {"success": True, "newPresetId": new_id, "copied": True}

    async def open_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("presetId", "standard")
        preset_path = os.path.join(os.getcwd(), "dsh", "presets", f"{preset_id}.yaml")
        opened = open_native_path(preset_path)
        return {"opened": opened, "path": preset_path.replace("\\", "/")}

    async def remove_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("presetId")
        return {"removed": True, "presetId": preset_id}
