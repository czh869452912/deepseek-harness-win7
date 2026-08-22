"""
ACP turn ending codec matching reference/packages/acp/acp/src/codec.ts
"""
from typing import Any, Dict


def turn_end_to_stop_reason(reason: Any) -> str:
    """
    Map harness turn end outcome to closest legal ACP stop reason.
    """
    kind = reason.get("kind") if isinstance(reason, dict) else getattr(reason, "kind", "completed")
    if kind == "completed":
        return "end_turn"
    elif kind == "max-tokens":
        return "max_tokens"
    elif kind == "aborted":
        return "end_turn"
    elif kind == "interrupted":
        return "cancelled"
    elif kind in ("blocked", "error"):
        return "end_turn"
    else:
        return "end_turn"
