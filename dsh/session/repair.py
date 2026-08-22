"""
Crash-recovery repair for an interrupted session log.
Supplies missing tool, step, and turn boundaries needed to resume with a valid transcript.
Aligned 1:1 with official `@deepseek-ai/dsh-session/repair`.
"""

import time
from typing import Any, Dict, List, Optional


TOOL_NOT_STARTED = "TOOL_NOT_STARTED"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"


def interrupted_turn_closers(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return deterministic synthetic events that close an open tail turn.
    """
    open_turn: Optional[int] = None
    open_step: Optional[int] = None
    pending_calls: Dict[str, Dict[str, Any]] = {}

    for event in events:
        ev_type = event.get("type")
        data = event.get("data", {})
        if ev_type == "turn/start":
            open_turn = data.get("turn")
            open_step = None
            pending_calls.clear()
        elif ev_type == "turn/end":
            open_turn = None
            open_step = None
            pending_calls.clear()
        elif ev_type == "step/start":
            open_step = data.get("step")
        elif ev_type == "step/end":
            pending_calls.clear()
            open_step = None
        elif ev_type == "assistant/message":
            msg = data.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool-call":
                    cid = block.get("id") or block.get("call_id")
                    if cid:
                        pending_calls[cid] = {"step": data.get("step")}
            # Also check tool_calls field
            for tcall in msg.get("tool_calls", []):
                cid = tcall.get("id")
                if cid:
                    pending_calls[cid] = {"step": data.get("step")}
        elif ev_type == "tool/call":
            cid = data.get("callId") or data.get("call_id")
            if cid and cid in pending_calls:
                pending_calls[cid]["call_seq"] = event.get("seq")
        elif ev_type == "tool/result":
            cid = data.get("tool_call_id") or data.get("callId")
            msg = data.get("message", {})
            if isinstance(msg, dict):
                src = msg.get("source", {})
                if isinstance(src, dict) and src.get("callId"):
                    cid = src.get("callId")
            if cid and cid in pending_calls:
                del pending_calls[cid]

    if open_turn is None or not events:
        return []

    last = events[-1]
    last_seq = last.get("seq", len(events))
    last_time = last.get("time", int(time.time() * 1000))

    seq = last_seq + 1
    closers: List[Dict[str, Any]] = []

    for call_id, entry in pending_calls.items():
        step = entry.get("step", open_step or 1)
        started = "call_seq" in entry
        call_seq = entry.get("call_seq")

        text = (
            "The tool call was interrupted after it was recorded, but no result was durably recorded. "
            "Its outcome is unknown. Decide whether to retry from the tool semantics: retry only if the operation is "
            "read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly."
            if started
            else "The tool call was interrupted before the Harness recorded it as started. Retry it if it is still needed."
        )

        error_info = (
            {"name": "ToolOutcomeUnknownError", "code": TOOL_OUTCOME_UNKNOWN}
            if started
            else {"name": "ToolNotStartedError", "code": TOOL_NOT_STARTED}
        )

        closer_ev = {
            "type": "tool/result",
            "seq": seq,
            "time": last_time,
            "data": {
                "turn": open_turn,
                "step": step,
                "tool_call_id": call_id,
                "message": {
                    "id": f"interrupted-tool-result-{call_id}-{seq}",
                    "role": "user",
                    "source": {"kind": "tool", "callId": call_id},
                    "content": [{
                        "type": "tool-result",
                        "toolCallId": call_id,
                        "isError": True,
                        "content": [{"type": "text", "text": text}],
                    }],
                },
                "error": error_info,
            },
            "surfaceOp": "append",
        }
        if started and call_seq is not None:
            closer_ev["sourceEventSeqs"] = [call_seq]

        closers.append(closer_ev)
        seq += 1

    if open_step is not None:
        closers.append({
            "type": "step/end",
            "seq": seq,
            "time": last_time,
            "data": {"turn": open_turn, "step": open_step},
        })
        seq += 1

    closers.append({
        "type": "turn/end",
        "seq": seq,
        "time": last_time,
        "data": {"turn": open_turn, "reason": {"kind": "interrupted"}},
    })

    return closers


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


def migrate_legacy_event(event: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    ev = migrate_legacy_turn_start_event(event, session_id)
    ev = migrate_legacy_turn_end_event(ev, session_id)
    ev = migrate_legacy_steering_event(ev, session_id)
    return ev
