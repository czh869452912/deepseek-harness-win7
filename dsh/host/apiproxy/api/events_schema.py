"""
Events Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/events.schema`).
Aligned 1:1 with reference `api/events.schema.ts`.
"""

from typing import Any, Dict, Tuple


def validate_event_frame(frame: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(frame, dict):
        return False, "Frame must be a dict"
    return True, ""
