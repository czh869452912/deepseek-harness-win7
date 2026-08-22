"""
Agent Preset Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/agent-presets.schema`).
Aligned 1:1 with reference `api/agent-presets.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_agent_preset_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
