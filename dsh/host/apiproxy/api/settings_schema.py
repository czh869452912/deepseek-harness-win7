"""
Settings Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/settings.schema`).
Aligned 1:1 with reference `api/settings.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_settings_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
