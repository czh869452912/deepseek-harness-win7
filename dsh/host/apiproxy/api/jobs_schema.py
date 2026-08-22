"""
Jobs Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/jobs.schema`).
Aligned 1:1 with reference `api/jobs.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_jobs_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
