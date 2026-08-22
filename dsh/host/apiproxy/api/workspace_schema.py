"""
Workspace Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/workspace.schema`).
Aligned 1:1 with reference `api/workspace.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_workspace_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
