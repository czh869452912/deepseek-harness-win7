"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session request-header.
Matching packages/core/session/tests/request-header.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
from typing import Any, Dict, List, Optional
import pytest

from dsh.core.session import (
    Session,
    SessionId,
    canonical_header,
    canonicalHeader,
    fold_request_header,
    foldRequestHeader,
    header_equals,
    headerEquals,
)
from dsh.llm.message import create_user_message, createUserMessage


CONFIG = {"provider": "mock", "model": "m"}


def tool(name: str, description: str = "d") -> Dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object"}}


class TestCanonicalHeader:
    def test_normalizes_empty_optional_fields_to_absence_and_preserves_populated_fields(self):
        assert canonical_header({
            "config": CONFIG,
            "adapterDefaults": {},
            "system": "",
            "tools": [],
        }) == {"config": CONFIG}

        full = canonical_header({
            "config": dict(CONFIG, maxTokens=256000),
            "adapterDefaults": {"maxTokens": True},
            "system": "s",
            "tools": [tool("a")],
        })
        assert full == {
            "config": dict(CONFIG, maxTokens=256000),
            "adapterDefaults": {"maxTokens": True},
            "system": "s",
            "tools": [tool("a")],
        }


class TestHeaderEquals:
    base = canonical_header({"config": CONFIG, "system": "s", "tools": [tool("a")]})

    def test_compares_every_canonical_field_and_preserves_tool_order(self):
        base = dict(self.base)
        assert header_equals(base, copy.deepcopy(base)) is True
        assert header_equals(base, dict(base, config={"provider": "mock", "model": "other"})) is False
        assert header_equals(base, dict(base, config=dict(base["config"], reasoningEffort="high"))) is False
        assert header_equals(
            dict(base, config=dict(base["config"], maxTokens=256000)),
            dict(base, config=dict(base["config"], maxTokens=256000), adapterDefaults={"maxTokens": True}),
        ) is False
        assert header_equals(base, dict(base, system="other")) is False
        assert header_equals(base, dict(base, tools=[])) is False
        assert header_equals(base, dict(base, tools=[tool("a", "changed")])) is False
        assert header_equals(
            {"config": CONFIG, "tools": [tool("a"), tool("b")]},
            {"config": CONFIG, "tools": [tool("b"), tool("a")]},
        ) is False

    def test_treats_absent_and_empty_tool_arrays_as_equivalent_canonical_absence(self):
        assert header_equals({"config": CONFIG}, {"config": CONFIG, "tools": []}) is True


class TestFoldRequestHeader:
    def test_returns_the_supplied_baseline_when_no_snapshot_follows(self):
        from_hdr = {"config": CONFIG, "system": "baseline"}
        unrelated = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
        ]
        assert fold_request_header(unrelated) is None
        assert fold_request_header(unrelated, from_hdr) == from_hdr

    def test_takes_the_latest_full_snapshot_and_skips_unrelated_events(self):
        session = Session.create(SessionId("fold"))
        session.append("turn/start", {"turn": 1})
        session.append("request/header", {"header": {"config": CONFIG, "system": "first"}, "reason": "initial"})
        session.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "hi"}], "source": {"kind": "user"},
        }), surface_op="append")
        session.append("request/header", {"header": {"config": {"provider": "mock", "model": "other"}, "tools": []}, "reason": "change"})
        assert fold_request_header(session.events) == {"config": {"provider": "mock", "model": "other"}}


class TestLegacyRequestHeaderFormat:
    def test_rejects_request_header_delta_in_seeds_and_untyped_appends(self):
        legacy = [{
            "type": "request/header-delta", "seq": 0, "time": 1, "data": {"config": CONFIG},
        }]
        with pytest.raises(ValueError, match=r"unsupported legacy request/header-delta"):
            Session.create(SessionId("legacy"), legacy)

        session = Session.create(SessionId("legacy-append-delta"))
        with pytest.raises(ValueError, match=r"unsupported legacy request/header-delta"):
            session.append("request/header-delta", {"config": CONFIG})
        assert len(session.events) == 0

    def test_rejects_the_removed_fallback_reason_in_seeds_and_untyped_appends(self):
        legacy = [{
            "type": "request/header", "seq": 0, "time": 1, "data": {"header": {"config": CONFIG}, "reason": "fallback"},
        }]
        with pytest.raises(ValueError, match=r'unsupported legacy request/header reason "fallback"'):
            Session.create(SessionId("legacy-seed-reason"), legacy)

        session = Session.create(SessionId("legacy-append-reason"))
        with pytest.raises(ValueError, match=r'unsupported legacy request/header reason "fallback"'):
            session.append("request/header", {"header": {"config": CONFIG}, "reason": "fallback"})
        assert len(session.events) == 0


class TestSessionRequestContext:
    CAPACITY = {"provider": "mock", "model": "m", "contextWindow": 128000}

    @staticmethod
    def seed_with(*records: Dict[str, Any]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = [{
            "type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1},
        }]
        for data in records:
            events.append({"type": "request/context", "seq": len(events), "time": 1, "data": data})
        return events

    def test_reads_undefined_before_any_record_exists(self):
        assert Session.create(SessionId("no-capacity")).request_context() is None

    def test_folds_a_seeded_log_on_first_read_taking_the_last_record(self):
        session = Session.create(
            SessionId("seeded-capacity"),
            self.seed_with(self.CAPACITY, dict(self.CAPACITY, model="later", contextWindow=256000)),
        )
        assert session.request_context() == {"provider": "mock", "model": "later", "contextWindow": 256000}

    def test_advances_incrementally_across_appends_and_skips_unrelated_events(self):
        session = Session.create(SessionId("incremental-capacity"), self.seed_with(self.CAPACITY))
        assert session.request_context() == self.CAPACITY
        session.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "unrelated"}], "source": {"kind": "user"},
        }), surface_op="append")
        assert session.request_context() == self.CAPACITY
        session.append("request/context", dict(self.CAPACITY, model="next", contextWindow=64000))
        assert session.request_context() == {"provider": "mock", "model": "next", "contextWindow": 64000}
        session.append("request/context", {"provider": "mock", "model": "unknown"})
        assert session.request_context() == {"provider": "mock", "model": "unknown"}

    def test_folds_a_batch_appended_between_two_reads(self):
        session = Session.create(SessionId("batched-capacity"), self.seed_with(self.CAPACITY))
        assert session.request_context() == self.CAPACITY
        session.append("request/context", dict(self.CAPACITY, contextWindow=200000))
        session.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "unrelated"}], "source": {"kind": "user"},
        }), surface_op="append")
        session.append("request/context", dict(self.CAPACITY, contextWindow=300000))
        ctx = session.request_context()
        assert ctx is not None
        assert ctx.get("contextWindow") == 300000

    def test_exposes_a_frozen_record_so_a_reader_cannot_desync_later_comparisons(self):
        session = Session.create(SessionId("frozen-capacity"), self.seed_with(self.CAPACITY))
        held = session.request_context()
        assert held is not None
        with pytest.raises(TypeError):
            held["contextWindow"] = 1


class TestReferenceFoldShape:
    """`foldRequestHeader` reads `event.data.header` unconditionally and folds it
    through `canonicalHeader` (request-header.ts:69). No upstream case covers a
    `request/header` event without a header record: the fold must fail loudly
    rather than skip the event and return a stale header."""

    def test_fails_loudly_when_a_request_header_event_carries_no_header_record(self):
        events = [{"type": "request/header", "seq": 0, "time": 1, "data": {"reason": "initial"}}]
        # JavaScript throws `TypeError: Cannot read properties of undefined`;
        # Python's closest native failures are KeyError/AttributeError for the
        # same malformed durable record (LEGAL_ADAPTATION: loud, not silent).
        with pytest.raises((KeyError, AttributeError, TypeError)):
            fold_request_header(events)
