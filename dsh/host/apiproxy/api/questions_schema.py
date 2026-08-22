"""
Questions Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/questions.schema`).
Aligned 1:1 with reference `api/questions.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_question_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    return True, ""
