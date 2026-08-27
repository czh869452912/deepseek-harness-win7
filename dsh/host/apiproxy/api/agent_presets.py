"""
Agent Preset Domain Handler (`@deepseek-ai/dsh-apiproxy/api/agent-presets`).
Handles `agentPreset.list`, `agentPreset.select`, `agentPreset.read`, `agentPreset.copy`, `agentPreset.openDocument`, `agentPreset.remove`.
Aligned 1:1 with reference `api/agent-presets.ts`.
Python 3.8.10 compatible.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.host.apiproxy.native_path_opener import open_native_path
from dsh.presets import (
    AgentPreset,
    AgentPresets,
    InvalidPresetIdError,
    PresetExistsError,
    PresetMountError,
    PresetNotWritableError,
    UnknownPresetError,
)


class AgentPresetsDomainHandler:
    """Handler for agentPreset.* RPC methods."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._service: Optional[AgentPresets] = None

    def _get_service(self) -> AgentPresets:
        if self._service is not None:
            return self._service

        if hasattr(self.ctx, "get"):
            svc = self.ctx.get("agent_presets") or self.ctx.get("agentPresets")
            if svc is not None:
                self._service = svc
                return svc

        # Standalone API consumers (for example tests or an embedded host)
        # still need the deployment roster.  Mirror profile-boot's system
        # root and default instead of creating an empty, detached service.
        shipped_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "presets"))
        self._service = AgentPresets(self.ctx, config={
            "default": "standard",
            "roots": [{"path": shipped_root, "trust": "system"}],
            "includeUserRoot": True,
        })
        return self._service

    async def list_presets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        service = self._get_service()
        presets = await service.list()

        entries: List[Dict[str, Any]] = []
        for p in presets:
            entry: Dict[str, Any] = {
                "id": p.id,
                "trust": p.trust,
                "isDefault": (p.id == service.default_id),
            }
            if p.name:
                entry["name"] = p.name
            if p.description:
                entry["description"] = p.description
            if p.broken:
                entry["broken"] = p.broken
            entries.append(entry)

        return {
            "presets": entries,
            "authorable": service.authorable,
            "hasDocument": True,
        }

    async def select_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId") or payload.get("preset")
        if not preset_id or not isinstance(preset_id, str):
            raise ValueError("bad-request: agentPreset must be non-empty string")

        service = self._get_service()

        session_id = payload.get("sessionId")
        sessions_svc = self.ctx.get("sessions") if hasattr(self.ctx, "get") else None
        if sessions_svc and session_id and hasattr(sessions_svc, "_sessions") and session_id in sessions_svc._sessions:
            s = sessions_svc._sessions[session_id]
            is_blank = not any(
                isinstance(ev, dict) and ev.get("type") == "turn/start"
                for ev in getattr(s, "events", [])
            )
            if not is_blank:
                raise ValueError(f"agent-preset-locked: Session '{session_id}' conversation has already started")
            s.header.agent_preset = preset_id

        try:
            p = await service.resolve_mountable(preset_id)
        except UnknownPresetError as err:
            available = [x.id for x in await service.list()]
            raise ValueError(f"agent-preset-not-found: unknown preset '{preset_id}' available: {available}")
        except PresetMountError as err:
            raise ValueError(f"agent-preset-invalid: preset '{preset_id}' is broken: {err.reason}")

        if hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("agent-preset/selected", session_id, preset_id)
            except Exception:
                pass

        return {"agentPreset": preset_id}

    async def read_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId")
        if not preset_id or not isinstance(preset_id, str):
            raise ValueError("bad-request: agentPreset must be non-empty string")

        service = self._get_service()
        try:
            p = await service.resolve(preset_id)
            content = await service.read(preset_id)
        except UnknownPresetError:
            raise ValueError(f"agent-preset-not-found: unknown preset '{preset_id}'")

        res: Dict[str, Any] = {
            "agentPreset": p.id,
            "trust": p.trust,
            "content": content,
        }
        if p.name:
            res["name"] = p.name
        if p.description:
            res["description"] = p.description
        return res

    async def copy_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        src_id = payload.get("from") or payload.get("sourcePresetId")
        target_id = payload.get("agentPreset") or payload.get("newPresetId")
        name = payload.get("name")

        if not src_id or not isinstance(src_id, str):
            raise ValueError("bad-request: from must be non-empty string")
        if not target_id or not isinstance(target_id, str):
            raise ValueError("bad-request: agentPreset must be non-empty string")

        service = self._get_service()

        try:
            await service.copy(src_id, target_id, name)
        except UnknownPresetError:
            raise ValueError(f"agent-preset-not-found: source preset '{src_id}' not found")
        except PresetExistsError:
            raise ValueError(f"agent-preset-conflict: preset '{target_id}' already exists")
        except InvalidPresetIdError as err:
            raise ValueError(f"bad-request: {err}")

        return {"agentPreset": target_id}

    async def open_document(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId")
        if not preset_id or not isinstance(preset_id, str):
            raise ValueError("bad-request: agentPreset must be non-empty string")

        service = self._get_service()
        try:
            p = await service.resolve(preset_id)
        except UnknownPresetError:
            raise ValueError(f"agent-preset-not-found: unknown preset '{preset_id}'")

        if p.trust == "system":
            return {"opened": False, "path": p.path.replace("\\", "/")}

        target_dir = os.path.dirname(p.path)
        if not os.path.isdir(target_dir):
            return {"opened": False, "path": target_dir.replace("\\", "/")}

        opened = open_native_path(target_dir)
        if opened:
            return {"opened": True}
        return {"opened": False, "path": target_dir.replace("\\", "/")}

    async def remove_preset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        preset_id = payload.get("agentPreset") or payload.get("presetId")
        if not preset_id or not isinstance(preset_id, str):
            raise ValueError("bad-request: agentPreset required")

        service = self._get_service()

        try:
            await service.remove(preset_id)
        except UnknownPresetError:
            raise ValueError(f"agent-preset-not-found: unknown preset '{preset_id}'")
        except PresetNotWritableError:
            raise ValueError(f"agent-preset-read-only: shipped preset '{preset_id}' cannot be removed")

        return {}
