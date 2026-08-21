import pytest
from dsh.cordis.context import Context
from dsh.session.session_query import SessionQueryService
from dsh.session.repair import interrupted_turn_closers, TOOL_NOT_STARTED, TOOL_OUTCOME_UNKNOWN
from dsh.core.session import Session, SessionHeader


def test_session_repair_interrupted_turn():
    # Simulate a session log where tool call was interrupted mid-turn
    events = [
        {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
        {"type": "step/start", "seq": 1, "time": 1001, "data": {"turn": 1, "step": 1}},
        {"type": "assistant/message", "seq": 2, "time": 1002, "data": {
            "turn": 1, "step": 1,
            "message": {
                "role": "assistant",
                "content": [{"type": "tool-call", "id": "call-interrupted-1", "name": "pwsh"}],
            }
        }},
        {"type": "tool/call", "seq": 3, "time": 1003, "data": {"turn": 1, "step": 1, "callId": "call-interrupted-1", "name": "pwsh"}},
        # Crash happened here: no tool/result, no step/end, no turn/end
    ]

    closers = interrupted_turn_closers(events)
    assert len(closers) >= 3  # tool/result, step/end, turn/end

    # Check synthetic tool result
    tool_res = [c for c in closers if c["type"] == "tool/result"][0]
    assert tool_res["data"]["tool_call_id"] == "call-interrupted-1"
    assert tool_res["data"]["error"]["code"] == TOOL_OUTCOME_UNKNOWN

    # Check step/end and turn/end
    types = [c["type"] for c in closers]
    assert types == ["tool/result", "step/end", "turn/end"]


def test_session_query_fts_search():
    ctx = Context()
    sqs = SessionQueryService(ctx, db_path=":memory:")

    sqs.index_event("session-1", {
        "type": "user/message",
        "seq": 1,
        "time": 1000,
        "data": {"turn": 1, "step": 1, "message": {"content": "How do I configure nginx reverse proxy on Windows?"}}
    })

    sqs.index_event("session-2", {
        "type": "user/message",
        "seq": 1,
        "time": 2000,
        "data": {"turn": 1, "step": 1, "message": {"content": "Let us implement cordis plugin dependency injection."}}
    })

    hits = sqs.search_sessions("nginx")
    assert len(hits) == 1
    assert hits[0]["sessionId"] == "session-1"

    hits_cordis = sqs.search_sessions("cordis")
    assert len(hits_cordis) == 1
    assert hits_cordis[0]["sessionId"] == "session-2"
