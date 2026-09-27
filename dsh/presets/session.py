"""
Session preset resolution helper.
1:1 with reference @deepseek-ai/dsh-agent-presets/session.ts.
Python 3.8.10 compatible.
"""

from typing import Any, Optional


def resolve_session_preset(session: Any) -> Optional[str]:
    """
    The preset a session actually runs, newest selection winning.
    Reconstruction reads resolve_session_preset, never the header alone.
    """
    events = (session.get("events", []) if isinstance(session, dict)
              else getattr(session, "events", [])) or []
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if isinstance(event, dict):
            ev_type = event.get("type")
            data = event.get("data") or {}
        else:
            ev_type = getattr(event, "type", None)
            data = getattr(event, "data", {}) or {}

        if ev_type == "agent-preset/selected" and isinstance(data, dict):
            p = data.get("agentPreset")
            if p:
                return p

    header = session.get("header") if isinstance(session, dict) else getattr(session, "header", None)
    if header is not None:
        if isinstance(header, dict):
            return header.get("agentPreset") or header.get("agent_preset")
        return getattr(header, "agent_preset", None) or getattr(header, "agentPreset", None)

    return None
