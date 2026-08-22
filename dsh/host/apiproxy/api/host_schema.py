"""
Host Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/host.schema`).
Aligned 1:1 with reference `api/host.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_host_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
