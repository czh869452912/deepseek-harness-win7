"""
Crash-recovery repair for an interrupted session log.
Supplies missing tool, step, and turn boundaries needed to resume with a valid transcript.
Ported 1:1 from reference packages/core/session/src/repair.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional, Sequence

TOOL_NOT_STARTED = "TOOL_NOT_STARTED"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"


def interrupted_turn_closers(events: Sequence[Dict[str, Any]], format_version: int = 3) -> List[Dict[str, Any]]:
    """
    Return deterministic synthetic events that close an open tail turn.
    Unmatched calls receive error results first, followed by an open step/end and an
    interrupted turn/end; sequences continue the log and timestamps reuse the
    last real event. A balanced or empty log returns no events.
    1:1 aligned with reference `interruptedTurnClosers(events)`.
    """
    if format_version == 4:
        return open_turn_closers(events, dict(kind='interrupted'))
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


_CLOSER_TEXT = {
    'interrupted': {
        'started': 'The tool call was interrupted after it was recorded, but no result was durably recorded. Its outcome is unknown. Decide whether to retry from the tool semantics: retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly.',
        'notStarted': 'The tool call was interrupted before the Harness recorded it as started. Retry it if it is still needed.',
    },
    'forked': {
        'started': 'The history inherited by this branch records this tool call starting but does not include its result. The parent session may have completed it after the fork point. Decide whether to retry from the tool semantics: retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly.',
        'notStarted': 'The history inherited by this branch has no record of this tool call starting. The parent session may have executed it after the fork point. Decide whether to retry from the tool semantics: retry only if the operation is read-only or idempotent; if it may have side effects, first verify external state or ask the user. Do not retry blindly.',
    },
}


class ToolCallRecovery:
    """Track only pending identities for a live step or V4 replay prefix."""
    def __init__(self, cause=None):
        self.cause = cause or dict(kind='interrupted')
        self.pending = {}
        self.last = None

    def observe(self, event):
        self.last = dict(seq=event['seq'], time=event['time'])
        kind, data = event['type'], event['data']
        if kind in ('turn/start', 'turn/end', 'step/end'):
            self.pending.clear()
        elif kind == 'assistant/message':
            for block in data['message']['content']:
                if block['type'] == 'tool-call':
                    self.pending[block['id']] = dict(turn=data['turn'], step=data['step'])
        elif kind == 'tool/call':
            entry = self.pending.get(data['callId'])
            if entry is not None:
                entry['callSeq'] = event['seq']
        elif kind == 'tool/result':
            call_id = data['message']['source']['callId']
            entry = self.pending.get(call_id)
            if (event.get('surfaceOp') == 'append' and entry is not None
                    and entry['turn'] == data['turn'] and entry['step'] == data['step']):
                del self.pending[call_id]

    def results(self):
        from dsh.core.session.json import deep_freeze
        if self.last is None:
            return []
        seq, output = self.last['seq'] + 1, []
        for call_id, entry in self.pending.items():
            started = 'callSeq' in entry
            message = deep_freeze(dict(id='%s-tool-result-%s-%s' % (self.cause['kind'], call_id, seq),
                role='tool', toolCallId=call_id, isError=True, source=dict(kind='tool', callId=call_id),
                content=[dict(type='text', text=_CLOSER_TEXT[self.cause['kind']]['started' if started else 'notStarted'])]))
            event = dict(type='tool/result', seq=seq, time=self.last['time'],
                         data=dict(turn=entry['turn'], step=entry['step'], message=message,
                                   error=dict(name='ToolOutcomeUnknownError' if started else 'ToolNotStartedError',
                                              code=TOOL_OUTCOME_UNKNOWN if started else TOOL_NOT_STARTED)), surfaceOp='append')
            if started:
                event['sourceEventSeqs'] = [entry['callSeq']]
            output.append(event)
            seq += 1
        return output


def open_turn_closers(events, cause):
    recovery = ToolCallRecovery(cause)
    turn = step = None
    for event in events:
        recovery.observe(event)
        kind, data = event['type'], event['data']
        if kind == 'turn/start':
            turn, step = data['turn'], None
        elif kind == 'turn/end':
            turn = step = None
        elif kind == 'step/start':
            step = data['step']
        elif kind == 'step/end':
            step = None
    if turn is None or not events:
        return []
    output = recovery.results()
    seq, time = events[-1]['seq'] + len(output) + 1, events[-1]['time']
    if step is not None:
        output.append(dict(type='step/end', seq=seq, time=time, data=dict(turn=turn, step=step)))
        seq += 1
    output.append(dict(type='turn/end', seq=seq, time=time, data=dict(turn=turn, reason=dict(kind=cause['kind']))))
    return output


openTurnClosers = open_turn_closers

