"""
Crash-recovery repair for an interrupted session log.
Supplies missing tool, step, and turn boundaries needed to resume with a valid transcript.
Aligned 1:1 with official `@deepseek-ai/dsh-session/repair`.
"""

import time
from typing import Any, Dict, List, Optional


from dsh.core.session.repair import (
    TOOL_NOT_STARTED,
    TOOL_OUTCOME_UNKNOWN,
    interrupted_turn_closers,
    interruptedTurnClosers,
)



def migrate_legacy_steering_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if event.get("type") != "steering/message":
        return event
    data = event.get("data", {})
    if not isinstance(data, dict):
        return event
    if "message" in data and isinstance(data["message"], dict):
        return {**event, "type": "user/message", "data": data["message"]}
    content = data.get("content", "")
    source = data.get("source")
    seq = event.get("seq", 0)
    return {
        **event,
        "type": "user/message",
        "data": {
            "id": f"legacy-message:{session_id}:{seq}",
            "role": "user",
            "content": content,
            "source": source,
        },
    }


def migrate_legacy_turn_start_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if event.get("type") != "turn/start":
        return event
    data = event.get("data")
    if not isinstance(data, dict) or "trigger" not in data:
        return event
    clean_data = dict(data)
    clean_data.pop("trigger", None)
    return {**event, "data": clean_data}


def migrate_legacy_turn_end_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if event.get("type") != "turn/end":
        return event
    data = event.get("data")
    if not isinstance(data, dict):
        return event
    reason = data.get("reason")
    if not isinstance(reason, dict):
        return event
    kind = reason.get("kind")
    if kind == "disposed":
        return {**event, "data": {**data, "reason": {"kind": "aborted", "reason": {"kind": "disposed"}}}}
    elif kind == "error" and "error" not in reason:
        err_msg = reason.get("message", "UNKNOWN")
        err_code = reason.get("code", "UNKNOWN")
        return {**event, "data": {**data, "reason": {"kind": "error", "error": {"message": err_msg, "code": err_code}}}}
    return event


def legacy_message_id(session_id: str, seq: int) -> str:
    return f"legacy-message:{session_id}:{seq}"


def migrate_legacy_message_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    etype = event.get("type")
    data = event.get("data")
    if not isinstance(data, dict):
        return event

    seq = event.get("seq", 0)

    if etype == "user/message":
        if "id" in data or "role" in data or "message" in data:
            return event
        if "content" not in data or "source" not in data:
            return event
        return {
            **event,
            "data": {
                **data,
                "id": legacy_message_id(session_id, seq),
                "role": "user",
            },
        }

    if etype == "assistant/message":
        if "message" in data or "content" not in data:
            return event
        content = data.get("content")
        provenance = data.get("provenance", {})
        prov_dict = dict(provenance) if isinstance(provenance, dict) else {}
        if "provider" not in prov_dict:
            prov_dict["provider"] = "unknown"
        if "model" not in prov_dict:
            prov_dict["model"] = "unknown"
        prov_dict["kind"] = "model"
        ev_data = {k: v for k, v in data.items() if k not in ("content", "provenance")}
        return {
            **event,
            "data": {
                **ev_data,
                "message": {
                    "id": legacy_message_id(session_id, seq),
                    "role": "assistant",
                    "content": content,
                    "source": prov_dict,
                },
            },
        }

    if etype == "tool/result":
        if "message" in data or "callId" not in data or "content" not in data or "isError" not in data:
            return event
        call_id = data.get("callId")
        content = data.get("content")
        is_error = data.get("isError")
        ev_data = {k: v for k, v in data.items() if k not in ("callId", "content", "isError")}
        return {
            **event,
            "data": {
                **ev_data,
                "message": {
                    "id": legacy_message_id(session_id, seq),
                    "role": "user",
                    "content": [{
                        "type": "tool-result",
                        "toolCallId": call_id,
                        "content": content,
                        "isError": is_error,
                    }],
                    "source": {
                        "kind": "tool",
                        "callId": call_id,
                    },
                },
            },
        }

    return event


def migrate_legacy_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    ev = migrate_legacy_turn_start_event(event, session_id)
    ev = migrate_legacy_turn_end_event(ev, session_id)
    ev = migrate_legacy_steering_event(ev, session_id)
    ev = migrate_legacy_message_event(ev, session_id)
    return ev
