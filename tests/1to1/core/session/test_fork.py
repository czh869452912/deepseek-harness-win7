"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/fork.
Matching packages/core/session/tests/fork.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Dict, List, Optional
import pytest

from dsh.cordis.context import Context
from dsh.core.session import Session, SessionForkError, SessionId, SessionPlugin, SessionStore
from dsh.llm.message import create_message, create_user_message, createMessage, createUserMessage


async def setup_sessions() -> Dict[str, Any]:
    ctx = Context()
    plugin = SessionPlugin()
    plugin.apply(ctx)
    sessions: SessionStore = ctx.get("sessions")
    return {"ctx": ctx, "sessions": sessions}


def append_closed_turn(
    session: Session,
    turn: int,
    text: Optional[str] = None,
    reason: Optional[Dict[str, Any]] = None,
) -> None:
    txt = text if text is not None else f"hello {turn}"
    rsn = reason if reason is not None else {"kind": "completed"}
    session.append("turn/start", {"turn": turn})
    session.append(
        "user/message",
        create_user_message({
            "content": [{"type": "text", "text": txt}],
            "source": {"kind": "user"},
        }),
        surface_op="append",
    )
    session.append("turn/end", {"turn": turn, "reason": rsn})


def append_open_turn(session: Session, turn: int) -> None:
    session.append("turn/start", {"turn": turn})
    session.append(
        "user/message",
        create_user_message({
            "content": [{"type": "text", "text": f"open {turn}"}],
            "source": {"kind": "user"},
        }),
        surface_op="append",
    )


def first_user_message(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    for e in events:
        if e.get("type") == "user/message":
            return e
    raise ValueError("missing user/message")


def last_seq(session: Session) -> int:
    events = session.events
    if not events:
        raise ValueError("missing last event")
    return events[-1]["seq"]


def inherited(session: Session) -> List[Dict[str, Any]]:
    events = session.events
    if not events or events[-1].get("type") != "session/end-seed":
        raise ValueError("seeded child is missing its end-seed marker")
    return events[:-1]


class TestSessionStoreFork:
    @pytest.mark.asyncio
    async def test_forks_an_empty_live_session_as_an_empty_child_with_lineage_metadata(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("empty-parent"), options={"meta": {"cwd": "/workspace"}})

        child = sessions.fork(source, None, SessionId("empty-child"))

        assert inherited(child) == []
        assert child.header.id == "empty-child"
        assert child.header.cwd == "/workspace"
        assert child.header.parent_session == "empty-parent"
        assert child.header.seed_length == 0

    @pytest.mark.asyncio
    async def test_forks_the_latest_completed_boundary_by_default(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("parent"), options={"meta": {"cwd": "/workspace"}})
        append_closed_turn(source, 1, "hello")

        child = sessions.fork(SessionId("parent"), None, SessionId("child"))

        assert inherited(child) == source.events
        assert child.events is not source.events
        assert child.events[1] is not source.events[1]

        assert first_user_message(source.events)["data"]["content"] == [{"type": "text", "text": "hello"}]
        assert first_user_message(child.events)["data"]["content"] == [{"type": "text", "text": "hello"}]
        assert child.header.id == "child"
        assert child.header.cwd == "/workspace"
        assert child.header.parent_session == "parent"
        assert child.header.seed_length == len(source.events)

    @pytest.mark.asyncio
    async def test_includes_stable_log_only_events_appended_after_a_closed_turn(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("log-only-parent"))
        append_closed_turn(source, 1, "hello")
        source.append("test/log-only", {"value": "after execution"})

        child = sessions.fork(source, None, SessionId("log-only-child"))

        assert inherited(child) == source.events
        assert inherited(child)[-1]["type"] == "test/log-only"
        assert inherited(child)[-1]["data"] == {"value": "after execution"}

    @pytest.mark.asyncio
    async def test_forks_from_an_earlier_turn_boundary_even_when_source_has_an_open_tail(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("parent"), options={"meta": {"cwd": "/workspace"}})
        append_closed_turn(source, 1, "first")
        first_boundary = last_seq(source)
        append_closed_turn(source, 2, "second")
        append_open_turn(source, 3)

        child = sessions.fork(source, first_boundary, SessionId("child-from-first"))

        assert inherited(child) == source.events[: first_boundary + 1]
        assert child.header.seed_length == first_boundary + 1
        messages = child.derive_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == [{"type": "text", "text": "first"}]

    @pytest.mark.asyncio
    async def test_accepts_every_turn_end_reason_as_an_explicit_fork_boundary(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        reasons = [
            {"kind": "completed"},
            {"kind": "aborted", "reason": {"kind": "user"}},
            {"kind": "error", "error": {"message": "model failed", "code": "UNKNOWN"}},
            {"kind": "aborted", "reason": {"kind": "disposed"}},
            {"kind": "max-tokens"},
            {"kind": "interrupted"},
        ]

        for index, reason in enumerate(reasons):
            source = sessions.create(SessionId(f"parent-{index}"))
            append_closed_turn(source, 1, reason["kind"], reason)

            child = sessions.fork(source, last_seq(source), SessionId(f"child-{index}"))

            assert inherited(child)[-1]["type"] == "turn/end"
            assert child.header.seed_length == len(source.events)

    @pytest.mark.asyncio
    async def test_marks_a_bracket_the_child_inherited_from_a_still_running_parent(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        parent = sessions.create(SessionId("bracket-parent"), options={"meta": {"cwd": "/workspace"}})
        append_closed_turn(parent, 1, "work")
        open_ev = parent.append("test/bracket-open", {"id": "op-1"})

        child = sessions.fork(parent, None, SessionId("bracket-child"))

        assert parent.events[-1] == open_ev
        assert not any(event["type"] == "session/end-seed" for event in parent.events)

        boundary = child.events[-1]
        assert boundary["type"] == "session/end-seed"
        assert boundary["seq"] > open_ev["seq"]
        assert child.first_live_seq == open_ev["seq"] + 1
        assert inherited(child)[-1]["type"] == "test/bracket-open"
        assert inherited(child)[-1]["data"] == {"id": "op-1"}

    @pytest.mark.asyncio
    async def test_rejects_invalid_boundaries_before_creating_a_child(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        empty = sessions.create(SessionId("empty"))
        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(empty, 0, SessionId("empty-child"))
        assert exc_info.value.code == "INVALID_BOUNDARY"
        assert 'fork boundary 0 does not exist in session "empty" (last seq: none)' in str(exc_info.value)
        assert sessions.get("empty-child") is None

        source = sessions.create(SessionId("parent"))
        append_closed_turn(source, 1)

        with pytest.raises(SessionForkError, match=r"non-negative safe integer"):
            sessions.fork(source, -1, SessionId("negative"))
        with pytest.raises(SessionForkError, match=r"non-negative safe integer"):
            sessions.fork(source, 9007199254740992, SessionId("unsafe"))
        with pytest.raises(SessionForkError) as exc_info2:
            sessions.fork(source, source.seq, SessionId("past-end"))
        assert exc_info2.value.code == "INVALID_BOUNDARY"
        assert f'fork boundary {source.seq} does not exist in session "parent"' in str(exc_info2.value)

    @pytest.mark.asyncio
    async def test_rejects_a_corrupted_live_source(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("corrupt-parent"))
        append_closed_turn(source, 1)
        source.log[2] = dict(source.log[2], seq=99)

        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(source, 2, SessionId("corrupt-child"))
        assert exc_info.value.code == "INVALID_BOUNDARY"
        assert 'fork boundary 2 does not match a contiguous event seq in session "corrupt-parent"' in str(exc_info.value)
        assert sessions.get("corrupt-child") is None

    @pytest.mark.asyncio
    async def test_rejects_an_unknown_live_session_id(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(SessionId("missing"))
        assert exc_info.value.code == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_rejects_a_detached_session_object(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        detached = Session.create(SessionId("detached"))
        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(detached)
        assert exc_info.value.code == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_rejects_a_stale_session_object(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        sessions.create(SessionId("same-id"))
        stale = Session.create(SessionId("same-id"))

        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(stale)
        assert exc_info.value.code == "SESSION_NOT_LIVE"

    @pytest.mark.asyncio
    async def test_rejects_selected_slices_whose_boundary_is_inside_an_open_turn(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]

        def case_turn_start(s: Session) -> int:
            s.append("turn/start", {"turn": 1})
            return last_seq(s)

        def case_step_start(s: Session) -> int:
            s.append("turn/start", {"turn": 1})
            s.append("step/start", {"turn": 1, "step": 1})
            return last_seq(s)

        def case_user_message(s: Session) -> int:
            s.append("turn/start", {"turn": 1})
            s.append("user/message", create_user_message({
                "content": [{"type": "text", "text": "open"}], "source": {"kind": "user"},
            }), surface_op="append")
            return last_seq(s)

        def case_assistant_message(s: Session) -> int:
            s.append("turn/start", {"turn": 1})
            s.append("step/start", {"turn": 1, "step": 1})
            s.append("assistant/message", {
                "turn": 1, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "partial"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            }, surface_op="append")
            return last_seq(s)

        def case_tool_call(s: Session) -> int:
            s.append("turn/start", {"turn": 1})
            s.append("step/start", {"turn": 1, "step": 1})
            s.append("assistant/message", {
                "turn": 1, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "call-open", "name": "bash", "arguments": "{}"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            }, surface_op="append")
            s.append("tool/call", {"turn": 1, "step": 1, "callId": "call-open", "name": "bash", "arguments": "{}"})
            return last_seq(s)

        cases = [
            ("turn/start", case_turn_start),
            ("step/start", case_step_start),
            ("user/message", case_user_message),
            ("assistant/message", case_assistant_message),
            ("tool/call", case_tool_call),
        ]

        for last_type, build in cases:
            source = sessions.create(SessionId(f"open-{last_type}"))
            boundary = build(source)

            with pytest.raises(SessionForkError) as exc_info:
                sessions.fork(source, boundary)
            assert exc_info.value.code == "OPEN_TURN"
            assert f'fork boundary {boundary} in session "open-{last_type}" ends inside open turn 1' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rejects_a_child_session_id_that_is_already_live(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("parent"))
        append_closed_turn(source, 1)
        sessions.create(SessionId("child"))

        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(source, None, SessionId("child"))
        assert exc_info.value.code == "SESSION_ALREADY_EXISTS"

    @pytest.mark.asyncio
    async def test_rejects_a_duplicate_child_session_id_before_validating_boundary(self):
        env = await setup_sessions()
        sessions: SessionStore = env["sessions"]
        source = sessions.create(SessionId("open-parent"))
        source.append("turn/start", {"turn": 1})
        sessions.create(SessionId("child"))

        with pytest.raises(SessionForkError) as exc_info:
            sessions.fork(source, None, SessionId("child"))
        assert exc_info.value.code == "SESSION_ALREADY_EXISTS"
