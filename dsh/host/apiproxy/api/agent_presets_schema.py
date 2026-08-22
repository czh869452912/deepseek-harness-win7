"""
Agent Preset Schema Validation (`@deepseek-ai/dsh-apiproxy/api/agent-presets.schema`).
1:1 with reference `api/agent-presets.schema.ts`.
"""

from typing import Any, Dict, List, Tuple


def _issue(path, message, code="invalid_type"):
    return {"code": code, "path": list(path), "message": message}


def validate_agent_preset_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    m = method.split(".")[-1].split("/")[-1] if method else ""
    issues = validate_by_method(m, payload)
    if issues:
        return False, str(issues)
    return True, ""


def validate_by_method(method: str, payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return [_issue([], "payload must be object")]
    if method == "list":
        return []
    if method == "select":
        issues = []
        sid = payload.get("sessionId")
        # reference schema requires sessionId min1, but current handler allows optional for backward compat; enforce if present
        if "sessionId" in payload and payload["sessionId"] is not None:
            if not isinstance(sid, str) or not sid.strip():
                issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        # agentPreset required min1 - check both naming variants
        preset = payload.get("agentPreset") or payload.get("presetId") or payload.get("preset")
        if not isinstance(preset, str) or not preset.strip():
            issues.append(_issue(["agentPreset"], "agentPreset must be non-empty string"))
        return issues
    if method in ("read", "openDocument", "open_document", "remove"):
        preset = payload.get("agentPreset") or payload.get("presetId")
        if not isinstance(preset, str) or not preset.strip():
            return [_issue(["agentPreset"], "agentPreset must be non-empty string")]
        return []
    if method == "copy":
        issues = []
        src = payload.get("from") or payload.get("sourcePresetId")
        if not isinstance(src, str) or not src.strip():
            issues.append(_issue(["from"], "from must be non-empty string"))
        dst = payload.get("agentPreset") or payload.get("newPresetId")
        if not isinstance(dst, str) or not dst.strip():
            issues.append(_issue(["agentPreset"], "agentPreset must be non-empty string"))
        return issues
    return []
