"""
Tool-pairing balance calculation over session surface nodes.
"""

from typing import Any, Dict, List, Optional


def event_delta(event: Dict[str, Any]) -> int:
    event_type = event.get("type", "")
    if event_type == "assistant/message":
        msg = event.get("data", {}).get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            return sum(1 for block in content if isinstance(block, dict) and block.get("type") == "tool-call")
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list):
            return len(tool_calls)
        return 0
    elif event_type == "tool/result":
        return -1
    return 0


def tool_pairing_balanced_before(session: Any, seq: int) -> bool:
    nodes = list(getattr(session.surface, "nodes", []))
    if seq not in nodes:
        raise ValueError(f"tool-pairing balance: surface seq {seq} not found")
    
    events = getattr(session, "events", [])
    in_progress = 0
    for s in nodes:
        if s == seq:
            break
        if s < len(events):
            evt = events[s]
            if isinstance(evt, dict):
                in_progress += event_delta(evt)
            elif hasattr(evt, "to_dict"):
                in_progress += event_delta(evt.to_dict())
    return in_progress == 0


def tool_pairing_balanced_after(session: Any, seq: int) -> bool:
    nodes = list(getattr(session.surface, "nodes", []))
    if seq not in nodes:
        raise ValueError(f"tool-pairing balance: surface seq {seq} not found")
    
    events = getattr(session, "events", [])
    in_progress = 0
    for s in nodes:
        if s < len(events):
            evt = events[s]
            if isinstance(evt, dict):
                in_progress += event_delta(evt)
            elif hasattr(evt, "to_dict"):
                in_progress += event_delta(evt.to_dict())
        if s == seq:
            break
    return in_progress == 0


# TS function names compatibility aliases
toolPairingBalancedBefore = tool_pairing_balanced_before
toolPairingBalancedAfter = tool_pairing_balanced_after
