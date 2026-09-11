"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/repair.
Matching packages/core/session/tests/repair.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List
import pytest

from dsh.core.session.repair import (
    TOOL_NOT_STARTED,
    TOOL_OUTCOME_UNKNOWN,
    interrupted_turn_closers,
)
from dsh.llm.message import create_message, create_tool_result_message


def user_turn_start(turn: int, seq: int) -> Dict[str, Any]:
    return {"type": "turn/start", "seq": seq, "time": seq, "data": {"turn": turn}}


class TestInterruptedTurnClosers:
    def test_returns_nothing_for_a_balanced_log(self):
        balanced = [
            user_turn_start(1, 0),
            {"type": "turn/end", "seq": 1, "time": 1, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        assert interrupted_turn_closers(balanced) == []

    def test_returns_nothing_for_an_empty_log(self):
        assert interrupted_turn_closers([]) == []

    def test_closes_an_open_turn_with_no_open_step(self):
        events = [user_turn_start(1, 0)]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["turn/end"]
        end = closers[0]
        assert end["seq"] == 1
        assert end["type"] == "turn/end"
        assert end["data"]["reason"] == {"kind": "interrupted"}

    def test_closes_an_open_step_before_the_turn(self):
        events = [
            user_turn_start(1, 0),
            {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["step/end", "turn/end"]
        assert [e["seq"] for e in closers] == [2, 3]

    def test_marks_an_assistant_tool_request_with_no_recorded_call_as_not_started(self):
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
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "calling a tool"},
                            {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {
                            "kind": "model",
                            "provider": "mock",
                            "model": "mock",
                        },
                    }),
                },
            },
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
        assert [e["seq"] for e in closers] == [3, 4, 5]
        result = closers[0]
        assert result["type"] == "tool/result"
        assert result["data"]["turn"] == 2
        assert result["data"]["step"] == 1
        assert result["data"]["message"]["source"]["callId"] == "call-1"
        assert result["data"]["message"]["content"][0]["isError"] is True
        assert result["data"]["error"]["code"] == TOOL_NOT_STARTED
        assert result["data"]["message"]["content"][0]["content"] == [{
            "type": "text",
            "text": "The tool call was interrupted before the Harness recorded it as started. Retry it if it is still needed.",
        }]

    def test_does_not_synthesize_a_result_for_a_tool_call_that_already_has_one(self):
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
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
            {
                "type": "tool/result",
                "seq": 3,
                "time": 3,
                "data": {
                    "turn": 2,
                    "step": 1,
                    "message": create_tool_result_message({
                        "callId": "call-1",
                        "content": [{"type": "text", "text": "ok"}],
                        "isError": False,
                    }),
                },
            },
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["step/end", "turn/end"]

    def test_does_not_synthesize_a_result_after_the_owning_step_already_closed(self):
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
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
            {"type": "step/end", "seq": 3, "time": 3, "data": {"turn": 2, "step": 1}},
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["turn/end"]
        assert closers[0]["seq"] == 4

    def test_synthesizes_results_only_for_the_still_open_turn(self):
        events = [
            user_turn_start(1, 0),
            {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 2,
                "time": 2,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "old-call", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
            {
                "type": "tool/result",
                "seq": 3,
                "time": 3,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": create_tool_result_message({
                        "callId": "old-call",
                        "content": [],
                        "isError": False,
                    }),
                },
            },
            {"type": "step/end", "seq": 4, "time": 4, "data": {"turn": 1, "step": 1}},
            {"type": "turn/end", "seq": 5, "time": 5, "data": {"turn": 1, "reason": {"kind": "completed"}}},
            user_turn_start(2, 6),
            {"type": "step/start", "seq": 7, "time": 7, "data": {"turn": 2, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 8,
                "time": 8,
                "data": {
                    "turn": 2,
                    "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "new-call", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
        assert closers[0]["data"]["message"]["source"]["callId"] == "new-call"

    def test_synthesizes_a_result_for_each_of_multiple_unanswered_calls_in_log_order(self):
        events = [
            user_turn_start(1, 0),
            {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 2,
                "time": 2,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "call-a", "name": "bash", "arguments": "{}"},
                            {"type": "tool-call", "id": "call-b", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
            {
                "type": "tool/result",
                "seq": 3,
                "time": 3,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": create_tool_result_message({
                        "callId": "call-a",
                        "content": [],
                        "isError": False,
                    }),
                },
            },
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
        assert closers[0]["data"]["message"]["source"]["callId"] == "call-b"

    def test_synthesized_tool_result_carries_surface_op_and_source_event_seqs(self):
        events = [
            user_turn_start(1, 0),
            {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 2,
                "time": 2,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [
                            {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                        ],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
            },
            {"type": "tool/call", "seq": 3, "time": 3, "data": {"turn": 1, "step": 1, "callId": "call-1", "name": "bash", "arguments": "{}"}},
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["tool/result", "step/end", "turn/end"]
        result = closers[0]
        assert result.get("surfaceOp") == "append"
        assert result.get("sourceEventSeqs") == [3]
        assert result["data"]["error"] == {
            "name": "ToolOutcomeUnknownError",
            "code": TOOL_OUTCOME_UNKNOWN,
        }
        text_content = result["data"]["message"]["content"][0]["content"][0]["text"]
        assert "retry only if the operation is read-only or idempotent" in text_content
        assert "first verify external state or ask the user" in text_content

    def test_handles_tool_call_without_a_matching_assistant_message_gracefully(self):
        events = [
            user_turn_start(1, 0),
            {"type": "step/start", "seq": 1, "time": 1, "data": {"turn": 1, "step": 1}},
            {"type": "tool/call", "seq": 2, "time": 2, "data": {"turn": 1, "step": 1, "callId": "orphan", "name": "bash", "arguments": "{}"}},
        ]
        closers = interrupted_turn_closers(events)
        assert [e["type"] for e in closers] == ["step/end", "turn/end"]
