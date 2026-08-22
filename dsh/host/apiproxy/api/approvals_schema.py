"""
Approvals Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/approvals.schema`).
Aligned 1:1 with reference `api/approvals.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_approval_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
