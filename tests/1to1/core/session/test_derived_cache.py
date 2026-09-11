"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session derived-message cache.
Matching packages/core/session/tests/derived-cache.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List
import pytest

from dsh.core.session import Session, SessionId
from dsh.llm.message import create_message, create_user_message, createMessage, createUserMessage


def user_text(session: Session, text: str) -> None:
    session.append(
        "user/message",
        create_user_message({
            "content": [{"type": "text", "text": text}],
            "source": {"kind": "user"},
        }),
        surface_op="append",
    )


def scratch(session: Session) -> List[Dict[str, Any]]:
    return Session.create(
        SessionId(f"{session.id}-scratch-{session.seq}"),
        list(session.events),
    ).derive_messages()


class TestDerivedMessageCache:
    def test_stays_deep_equal_to_a_from_scratch_replay_derivation_as_the_log_grows(self):
        session = Session.create(SessionId("cache-grow"))
        session.append("turn/start", {"turn": 1})
        user_text(session, "one")
        assert session.derive_messages() == scratch(session)

        user_text(session, "two")
        session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "reply"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        assert session.derive_messages() == scratch(session)

        session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 2,
                "message": create_message({
                    "role": "assistant",
                    "content": [],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
                "usage": {"inputTokens": 1, "outputTokens": 0},
            },
            surface_op="append",
        )
        assert session.derive_messages() == scratch(session)

    def test_rebuilds_on_a_surface_replace_and_still_matches_scratch(self):
        session = Session.create(SessionId("cache-replace"))
        session.append("turn/start", {"turn": 1})
        user_text(session, "one")
        user_text(session, "two")
        before_replace = session.derive_messages()
        assert len(before_replace) == 2

        nodes = session.surface.nodes
        session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "summary"}],
                "source": {"kind": "plugin", "plugin": "compact"},
            }),
            surface_op={"op": "replace", "start": nodes[0], "end": nodes[1]},
            source_event_seqs=[nodes[0], nodes[1]],
        )

        assert len(session.derive_messages()) == 1
        assert session.derive_messages() == scratch(session)
        assert len(before_replace) == 2

    def test_returns_a_fresh_array_per_call(self):
        session = Session.create(SessionId("cache-snapshot"))
        session.append("turn/start", {"turn": 1})
        user_text(session, "one")
        first = session.derive_messages()
        user_text(session, "two")
        second = session.derive_messages()
        assert len(first) == 1
        assert len(second) == 2


class TestSessionDeriveEventMessage:
    def test_projects_one_appended_event_exactly_as_the_full_derivation_projects_its_node(self):
        session = Session.create(SessionId("per-event"))
        session.append("turn/start", {"turn": 1})
        event = session.append(
            "user/message",
            create_user_message({
                "content": [{"type": "text", "text": "hi"}],
                "source": {"kind": "user"},
            }),
            surface_op="append",
        )
        assert session.derive_event_message(event) == session.derive_messages()[-1]

    def test_projects_null_for_events_that_produce_no_message(self):
        session = Session.create(SessionId("per-event-null"))
        session.append("turn/start", {"turn": 1})
        boundary = session.append("step/start", {"turn": 1, "step": 1})
        assert session.derive_event_message(boundary) is None

        empty = session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        assert session.derive_event_message(empty) is None
