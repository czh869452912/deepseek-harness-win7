"""
Crash-recovery repair for an interrupted session log.
Supplies missing tool, step, and turn boundaries needed to resume with a valid transcript.
Ported 1:1 from reference packages/core/session/src/repair.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional, Sequence

TOOL_NOT_STARTED = "TOOL_NOT_STARTED"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"


def interrupted_turn_closers(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return deterministic synthetic events that close an open tail turn.
    Unmatched calls receive error results first, followed by an open step/end and an
    interrupted turn/end; sequences continue the log and timestamps reuse the
    last real event. A balanced or empty log returns no events.
    1:1 aligned with reference `interruptedTurnClosers(events)`.
    """
    open_turn: Optional[int] = None
    open_step: Optional[int] = None
    # Reset at each turn boundary so earlier calls cannot leak into tail repair.
    # Maps callId -> {"step": step, "call_seq": optional int}
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
            # The assistant message carries the tool-call blocks; each is pending
            # until a `tool/result` event with the same callId is logged.
            msg = data.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool-call":
                        cid = block.get("id")
                        if cid:
                            pending_calls[cid] = {"step": data.get("step")}
        elif ev_type == "tool/call":
            # Cite the `tool/call` seq from the synthetic result.
            cid = data.get("callId")
            if cid and cid in pending_calls:
                pending_calls[cid]["call_seq"] = event.get("seq")
        elif ev_type == "tool/result":
            msg = data.get("message", {})
            cid = None
            if isinstance(msg, dict):
                src = msg.get("source", {})
                if isinstance(src, dict):
                    cid = src.get("callId")
            if cid and cid in pending_calls:
                del pending_calls[cid]

    # Balanced log (no crash mid-turn): nothing to close.
    if open_turn is None or not events:
        return []

    last = events[-1]
    last_seq = last.get("seq", len(events) - 1)
    last_time = last.get("time", 0)

    seq = last_seq + 1
    closers: List[Dict[str, Any]] = []

    # Close calls before their step: providers reject dangling assistant calls,
    # and dictionary insertion order preserves transcript order.
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

        closer_ev: Dict[str, Any] = {
            "type": "tool/result",
            "seq": seq,
            "time": last_time,
            "data": {
                "turn": open_turn,
                "step": step,
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

    # Close an open step next
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


# CamelCase alias
interruptedTurnClosers = interrupted_turn_closers

