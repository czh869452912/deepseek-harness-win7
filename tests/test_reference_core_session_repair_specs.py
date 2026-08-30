"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/repair (crash recovery closers)
matching reference/packages/core/session/tests/repair.spec.ts.
"""

import pytest
from dsh.session.repair import (
    interrupted_turn_closers,
    TOOL_NOT_STARTED,
    TOOL_OUTCOME_UNKNOWN,
)


def user_turn_start(turn: int, seq: int):
    return {"type": "turn/start", "seq": seq, "time": seq, "data": {"turn": turn}}


def test_interrupted_turn_closers_balanced_log():
    balanced = [
        user_turn_start(1, 0),
        {"type": "turn/end", "seq": 1, "time": 1, "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]
    assert interrupted_turn_closers(balanced) == []


def test_interrupted_turn_closers_empty_log():
    assert interrupted_turn_closers([]) == []


def test_interrupted_turn_closers_open_turn_no_open_step():
    events = [user_turn_start(1, 0)]
    closers = interrupted_turn_closers(events)
    assert [e["type"] for e in closers] == ["turn/end"]
    end = closers[0]
    assert end["seq"] == 1
    assert end["data"]["reason"] == {"kind": "interrupted"}


def test_interrupted_turn_closers_open_step_before_turn():
    events = [
        user_turn_start(1, 0),
        {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
    ]
    closers = interrupted_turn_closers(events)
    assert [e["type"] for e in closers] == ["step/end", "turn/end"]
    assert [e["seq"] for e in closers] == [2, 3]


def test_interrupted_turn_closers_tool_call_not_started():
    events = [
        user_turn_start(2, 0),
        {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 2, "step": 1}},
        {
            "type": "assistant/message",
            "seq": 2,
            "time": 2,
            "data": {
                "turn": 2,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "calling a tool"},
                        {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                    ],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                },
            },
        },
    ]
    closers = interrupted_turn_closers(events)
    assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
    assert [e["seq"] for e in closers] == [3, 4, 5]
    result = closers[0]
    assert result["data"]["turn"] == 2
    assert result["data"]["step"] == 1
    assert result["data"]["error"]["code"] == TOOL_NOT_STARTED


def test_interrupted_turn_closers_tool_call_started_outcome_unknown():
    events = [
        user_turn_start(2, 0),
        {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 2, "step": 1}},
        {
            "type": "assistant/message",
            "seq": 2,
            "time": 2,
            "data": {
                "turn": 2,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                    ],
                },
            },
        },
        {"type": "tool/call", "seq": 3, "time": 3, "data": {"turn": 2, "step": 1, "callId": "call-1", "name": "bash"}},
    ]
    closers = interrupted_turn_closers(events)
    assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
    assert [e["seq"] for e in closers] == [4, 5, 6]
    result = closers[0]
    assert result["data"]["error"]["code"] == TOOL_OUTCOME_UNKNOWN


def test_interrupted_turn_closers_skips_already_answered_tool_call():
    events = [
        user_turn_start(2, 0),
        {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 2, "step": 1}},
        {
            "type": "assistant/message",
            "seq": 2,
            "time": 2,
            "data": {
                "turn": 2,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                    ],
                },
            },
        },
        {"type": "tool/call", "seq": 3, "time": 3, "data": {"turn": 2, "step": 1, "callId": "call-1", "name": "bash"}},
        {
            "type": "tool/result",
            "seq": 4,
            "time": 4,
            "data": {
                "turn": 2,
                "step": 1,
                "callId": "call-1",
                "message": {"role": "user", "content": [{"type": "tool-result", "toolCallId": "call-1", "content": [{"type": "text", "text": "done"}]}]},
            },
        },
    ]
    closers = interrupted_turn_closers(events)
    # Only step/end and turn/end needed since tool was already answered
    assert [e["type"] for e in closers] == ["step/end", "turn/end"]
    assert [e["seq"] for e in closers] == [5, 6]
