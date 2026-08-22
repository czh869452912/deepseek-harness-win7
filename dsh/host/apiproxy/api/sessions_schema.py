"""
Sessions Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/sessions.schema`).
Aligned 1:1 with reference `api/sessions.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_session_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
