"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session core session and store.
Matching packages/core/session/tests/session.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
from typing import Any, Dict, List, Optional
import pytest

from dsh.cordis.context import Context
from dsh.core.session import (
    SESSION_FORMAT_VERSION,
    Session,
    SessionId,
    SessionPlugin,
    SessionStore,
    adopt_session_event,
    adoptSessionEvent,
    snapshot_session_event,
    snapshotSessionEvent,
    validate_restored_session_header,
    validate_session_header,
)
from dsh.llm.message import (
    create_message,
    create_tool_result_message,
    create_user_message,
    createMessage,
    createToolResultMessage,
    createUserMessage,
)


class TestSessionCore:
    def test_exposes_stable_surface_view(self):
        session = Session.create(SessionId("surface-view"))
        surface = session.surface
        assert surface is session.surface

    def test_derives_message_history_from_event_log(self):
        session = Session.create(SessionId("s1"))
        session.append("turn/start", {"turn": 1})
        session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "hello"}],
                "source": {"kind": "user"},
            }),
            surface_op="append",
        )
        session.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "hi"}})
        session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "let me check"},
                        {"type": "tool-call", "id": "c1", "name": "echo", "arguments": "{}"},
                    ],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        session.append(
            "tool/result",
            {
                "turn": 1,
                "step": 1,
                "message": create_tool_result_message({
                    "callId": "c1",
                    "content": [{"type": "text", "text": "ok"}],
                    "isError": False,
                }),
            },
            surface_op="append",
        )
        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

        messages = session.derive_messages()
        assert [m["role"] for m in messages] == ["user", "assistant", "user"]
        assert len(messages[1]["content"]) == 2
        assert messages[2]["content"][0]["type"] == "tool-result"
        assert messages[2]["content"][0]["toolCallId"] == "c1"

    def test_accepts_and_round_trips_max_tokens_turn_end_reason(self):
        session = Session.create(SessionId("s1"))
        session.append("turn/start", {"turn": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "max-tokens"}})

        turn_end = [e for e in session.events if e["type"] == "turn/end"][-1]
        assert turn_end["data"]["reason"] == {"kind": "max-tokens"}

    def test_round_trips_an_aborted_turn_with_its_cancellation_cause(self):
        session = Session.create(SessionId("aborted"))
        session.append("turn/start", {"turn": 1})
        session.append("turn/end", {"turn": 1, "reason": {"kind": "aborted", "reason": {"kind": "user"}}})

        replayed = Session.create(SessionId("aborted-replay"), copy.deepcopy(session.events))
        assert replayed.events[:-1] == session.events
        turn_end = [e for e in replayed.events if e["type"] == "turn/end"][-1]
        assert turn_end["data"]["reason"] == {"kind": "aborted", "reason": {"kind": "user"}}

    def test_renders_injected_context_and_user_messages_as_plain_user_content(self):
        session = Session.create(SessionId("s2"))
        session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "file changed: a.ts"}],
                "source": {"kind": "plugin", "plugin": "watcher"},
            }),
            surface_op="append",
        )
        session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "focus on tests"}],
                "source": {"kind": "user"},
            }),
            surface_op="append",
        )

        messages = session.derive_messages()
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == [{"type": "text", "text": "file changed: a.ts"}]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == [{"type": "text", "text": "focus on tests"}]

    def test_replays_identically_from_a_seeded_event_log(self):
        original = Session.create(SessionId("s3"))
        original.append("turn/start", {"turn": 1})
        original.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "q"}],
                "source": {"kind": "user"},
            }),
            surface_op="append",
        )
        original.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "a"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        original.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

        replayed = Session.create(SessionId("s3-replay"), list(original.events))
        assert replayed.derive_messages() == original.derive_messages()
        assert replayed.events[: original.seq] == original.events
        assert replayed.seq == original.seq + 1
        assert replayed.first_live_seq == original.seq

    def test_marks_an_explicitly_empty_seed_without_marking_a_fresh_session(self):
        fresh = Session.create(SessionId("fresh-empty"))
        assert fresh.events == []

        resumed = Session.create(SessionId("resumed-empty"), [])
        assert resumed.first_live_seq == 0
        assert resumed.events[0]["type"] == "session/end-seed"

        reopened = Session.create(SessionId("reopened-empty"), resumed.events)
        assert reopened.first_live_seq == 1
        assert reopened.events == resumed.events

    def test_rejects_pre_provider_request_headers_on_seed_load(self):
        request_header = {
            "type": "request/header",
            "seq": 0,
            "time": 1,
            "data": {"header": {"config": {"model": "old-model"}}, "reason": "initial"},
        }
        with pytest.raises(ValueError, match=r"seed request/header at index 0 lacks provider/model"):
            Session.create(SessionId("old-header"), [request_header])

    def test_rejects_event_specific_malformed_message_shapes(self):
        invalid = [
            (
                "user role",
                {
                    "type": "user/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "id": "u1",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "c"}],
                        "source": {"kind": "user"},
                    },
                },
                r'message must have role "user"',
            ),
            (
                "source",
                {
                    "type": "user/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "id": "u1",
                        "role": "user",
                        "content": [{"type": "text", "text": "c"}],
                        "source": None,
                    },
                },
                r"message has invalid source",
            ),
            (
                "content shape",
                {
                    "type": "user/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "id": "u1",
                        "role": "user",
                        "content": "not-an-array",
                        "source": {"kind": "user"},
                    },
                },
                r"message has invalid content",
            ),
        ]
        for name, ev, pattern in invalid:
            with pytest.raises(ValueError, match=pattern):
                Session.create(SessionId(f"invalid-{name}"), [ev])


class TestSessionStoreOperations:
    @pytest.mark.asyncio
    async def test_creates_and_lists_sessions(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        store: SessionStore = ctx.get("sessions")

        s1 = store.create(SessionId("store-1"))
        s2 = store.create(SessionId("store-2"))

        assert store.get("store-1") is s1
        assert store.get("store-2") is s2
        assert len(store.list()) == 2

    @pytest.mark.asyncio
    async def test_emits_session_created_and_session_event(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        store: SessionStore = ctx.get("sessions")

        events: List[Any] = []
        created: List[Any] = []

        ctx.on("session/created", lambda sess: created.append(sess.id))
        ctx.on("session/event", lambda sess, ev: events.append((sess.id, ev["type"])))

        session = store.create(SessionId("emitter"))
        session.append("turn/start", {"turn": 1})

        assert created == ["emitter"]
        assert events == [("emitter", "turn/start")]

    @pytest.mark.asyncio
    async def test_emits_session_disposed_on_detach(self):
        ctx = Context()
        SessionPlugin().apply(ctx)
        store: SessionStore = ctx.get("sessions")

        disposed: List[str] = []
        ctx.on("session/disposed", lambda s: disposed.append(s.id))

        prep = store.prepare(SessionId("disposed-sess"))
        detach = store.enter(prep)
        store.announce(prep)
        assert store.get("disposed-sess") is not None

        detach()
        assert store.get("disposed-sess") is None
        assert disposed == ["disposed-sess"]
