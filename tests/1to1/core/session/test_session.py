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

    def test_rejects_pre_provider_request_headers_and_assistant_messages_on_seed_load(self):
        request_header = {
            "type": "request/header",
            "seq": 0,
            "time": 1,
            "data": {"header": {"config": {"model": "old-model"}}, "reason": "initial"},
        }
        with pytest.raises(ValueError, match=r"seed request/header at index 0 lacks provider/model"):
            Session.create(SessionId("old-header"), [request_header])

        assistant_message = {
            "type": "assistant/message",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1, "step": 1, "content": [{"type": "text", "text": "old"}]},
            "surfaceOp": "append",
        }
        with pytest.raises(ValueError, match=r"seed assistant/message at index 0 lacks an identified message"):
            Session.create(SessionId("old-assistant"), [assistant_message])

        malformed_header = {
            "type": "request/header",
            "seq": 0,
            "time": 1,
            "data": {"header": "old-header"},
        }
        with pytest.raises(ValueError, match=r"seed request/header at index 0 lacks provider/model"):
            Session.create(SessionId("malformed-header"), [malformed_header])

        # A JSON `null` payload on an unrelated event type is adopted verbatim.
        unrelated_primitive_data = {"type": "plugin/event", "seq": 0, "time": 1, "data": None}
        session = Session.create(SessionId("primitive-plugin-data"), [unrelated_primitive_data])
        assert session.events[:1] == [unrelated_primitive_data]

    def test_rejects_event_specific_malformed_message_shapes_on_seed_load(self):
        user = {
            "id": "user",
            "role": "user",
            "content": [{"type": "text", "text": "content"}],
            "source": {"kind": "user"},
        }
        assistant = {
            "id": "assistant",
            "role": "assistant",
            "content": [{"type": "text", "text": "content"}],
            "source": {"kind": "model", "provider": "mock", "model": "mock"},
        }
        tool = {
            "id": "tool",
            "role": "user",
            "content": [{
                "type": "tool-result",
                "toolCallId": "call",
                "content": [{"type": "text", "text": "result"}],
            }],
            "source": {"kind": "tool", "callId": "call"},
        }
        invalid = [
            (
                "message record",
                {
                    "type": "user/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": None,
                },
                r"lacks an identified message",
            ),
            (
                "user role",
                {
                    "type": "user/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": dict(user, role="assistant"),
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
                    "data": dict(user, source=None),
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
                    "data": dict(user, content="not-an-array"),
                },
                r"message has invalid content",
            ),
            (
                "assistant source",
                {
                    "type": "assistant/message",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "turn": 1,
                        "step": 1,
                        "message": dict(assistant, source={"kind": "user"}),
                    },
                },
                r"message must have model source",
            ),
            (
                "tool source",
                {
                    "type": "tool/result",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "turn": 1,
                        "step": 1,
                        "message": dict(tool, source={"kind": "user"}),
                    },
                },
                r"message must have tool source",
            ),
            (
                "tool tuple",
                {
                    "type": "tool/result",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "turn": 1,
                        "step": 1,
                        "message": dict(tool, content=[{"type": "text", "text": "not a result"}]),
                    },
                },
                r"message must contain one tool-result block",
            ),
            (
                "tool correlation",
                {
                    "type": "tool/result",
                    "seq": 0,
                    "time": 1,
                    "surfaceOp": "append",
                    "data": {
                        "turn": 1,
                        "step": 1,
                        "message": dict(tool, source={"kind": "tool", "callId": "other-call"}),
                    },
                },
                r"message has mismatched tool call ids",
            ),
        ]
        for name, event, pattern in invalid:
            with pytest.raises(ValueError, match=pattern):
                Session.create(SessionId("invalid-{}".format(name)), [event])


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

    @pytest.mark.asyncio
    async def test_contains_a_reentrant_observer_append_without_reordering_later_observers(self):
        """
        reference session.spec.ts `contains a reentrant observer append without
        reordering later observers`.

        A reentrant append from inside a `session/event` observer is contained (the
        listener is reported through `ctx.logger.warn`, carrying the exact guard
        message) and the appended event is published to the remaining observers in
        registration order. The JS `String(error)` prefix `Error: ` is absent here
        because Python `str(exception)` carries no type prefix (LEGAL_ADAPTATION).
        """
        ctx = Context()
        SessionPlugin().apply(ctx)
        store: SessionStore = ctx.get("sessions")

        warnings: List[str] = []
        ctx.logger.warn = lambda message, *args: warnings.append(str(message))

        session = store.create(SessionId("reentrant-observer"))
        heard: List[Any] = []

        def reentrant_observer(observed_session, _event):
            # JS ignores the extra `event` callback argument; a Python callable must
            # declare both parameters (LEGAL_ADAPTATION, Python 3.8 has no JS-style
            # arity tolerance).
            observed_session.append("request/context", {"provider": "mock", "model": "mock"})

        ctx.on("session/event", reentrant_observer)
        ctx.on("session/event", lambda _observed_session, event: heard.append(event))

        appended = session.append("turn/start", {"turn": 1})

        assert session.events == [appended]
        assert heard == [appended]
        assert warnings == [
            'session "reentrant-observer": session/event listener threw: '
            "session append cannot reenter while another append is being published"
        ]

# ============================================================================
# session.spec.ts: Session seed/append validation, freezing, and headers
# ============================================================================

import asyncio  # noqa: E402
import re  # noqa: E402

from dsh.cordis.plugin import Plugin  # noqa: E402
from dsh.core.session.json import UNDEFINED, FrozenDict, FrozenList  # noqa: E402
from dsh.core.session.surface import SurfaceManager  # noqa: E402

MESSAGE_SOURCE = {"kind": "model", "provider": "mock", "model": "mock"}


def _is_frozen(value: Any) -> bool:
    """`Object.isFrozen(value)` for the values a session log can carry."""
    return isinstance(value, (FrozenDict, FrozenList))


def _make_store():
    ctx = Context()
    SessionPlugin().apply(ctx)
    return ctx, ctx.get("sessions")


def _text_message(text, message_id=None):
    message = {
        "content": [{"type": "text", "text": text}],
        "source": {"kind": "user"},
    }
    if message_id is not None:
        message["id"] = message_id
    return create_user_message(message)


def _assistant_message(text, message_id=None):
    message = {
        "content": [{"type": "text", "text": text}],
        "source": dict(MESSAGE_SOURCE),
    }
    if message_id is not None:
        message["id"] = message_id
    return create_message(dict(message, role="assistant"))


def _tool_message(call_id, text, message_id=None):
    message = {
        "callId": call_id,
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    if message_id is not None:
        message["id"] = message_id
    return create_tool_result_message(message)


class TestSessionSeedAndAppendValidation:
    def test_keeps_the_exact_identified_context_message_in_durable_history_and_projection(self):
        session = Session.create(SessionId("s2-raw"))
        message = _text_message(
            "<system-reminder>Additional instructions from: pkg/AGENTS.md</system-reminder>",
        )
        message["source"] = {"kind": "plugin", "plugin": "agent-instructions"}
        session.append("user/message", message, surface_op="append")

        assert session.derive_messages() == [message]
        event = session.events[0]
        assert event["data"]["source"] == {"kind": "plugin", "plugin": "agent-instructions"}

    def test_snapshots_message_events_without_validating_plugin_owned_block_details(self):
        boundary = snapshot_session_event({
            "type": "turn/start",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1},
        })
        assert boundary == {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}}

        extended = snapshot_session_event({
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "surfaceOp": "append",
            "data": {
                "id": "extended-message",
                "role": "user",
                "content": [{"type": "plugin-block", "value": 1}],
                "source": {"kind": "plugin-source", "value": 1},
            },
        })
        assert extended["data"]["content"] == [{"type": "plugin-block", "value": 1}]

    def test_adopts_exclusively_owned_messages_in_place_and_keeps_snapshots_detached(self):
        owned = {
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "surfaceOp": "append",
            "data": {
                "id": "owned-message",
                "role": "user",
                "content": [{"type": "text", "text": "owned"}],
                "source": {"kind": "user"},
            },
        }
        assert adopt_session_event(owned) is owned
        assert _is_frozen(owned["data"])
        assert _is_frozen(owned["data"]["content"])

        source = copy.deepcopy(owned)
        snapshot = snapshot_session_event(source)
        assert snapshot is not source
        assert snapshot["data"] is not source["data"]
        assert snapshot["data"]["content"] is not source["data"]["content"]

    def test_validates_message_shape_before_adopting_ownership(self):
        malformed = {
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "data": {
                "id": "wrong-role",
                "role": "assistant",
                "content": [],
                "source": {"kind": "user"},
            },
        }
        with pytest.raises(ValueError, match=r'message must have role "user"'):
            adopt_session_event(malformed)

    def test_round_trips_a_non_empty_reasoning_effort_and_rejects_invalid_durable_values(self):
        valid = {
            "type": "request/header",
            "seq": 0,
            "time": 1,
            "data": {
                "header": {
                    "config": {
                        "provider": "mock",
                        "model": "model",
                        "reasoningEffort": "adapter-owned",
                    },
                },
                "reason": "initial",
            },
        }
        assert Session.create(SessionId("reasoning-effort"), [valid]).events[0] == valid

        for reasoning_effort in ["", 1]:
            invalid = copy.deepcopy(valid)
            invalid["data"]["header"]["config"]["reasoningEffort"] = reasoning_effort
            with pytest.raises(
                ValueError, match="seed request/header at index 0 has an invalid reasoningEffort"
            ):
                Session.create(SessionId("invalid-reasoning-effort"), [invalid])

    def test_round_trips_adapter_default_markers_and_rejects_invalid_durable_values(self):
        valid = {
            "type": "request/header",
            "seq": 0,
            "time": 1,
            "data": {
                "header": {
                    "config": {
                        "provider": "mock",
                        "model": "model",
                        "maxTokens": 256000,
                    },
                    "adapterDefaults": {"maxTokens": True},
                },
                "reason": "initial",
            },
        }
        assert Session.create(SessionId("adapter-defaults"), [valid]).events[0] == valid

        for adapter_defaults in [
            None,
            [],
            {"unknown": True},
            {"maxTokens": False},
            {"reasoningEffort": True},
        ]:
            invalid = copy.deepcopy(valid)
            invalid["data"]["header"]["adapterDefaults"] = adapter_defaults
            with pytest.raises(
                ValueError, match="seed request/header at index 0 has invalid adapterDefaults"
            ):
                Session.create(SessionId("invalid-adapter-defaults"), [invalid])

    def test_isolates_the_log_from_mutation_through_a_derived_message(self):
        session = Session.create(SessionId("s4"))
        session.append("user/message", _text_message("original"), surface_op="append")
        session.append(
            "tool/result",
            {"turn": 1, "step": 1, "message": _tool_message("c1", "tool out")},
            surface_op="append",
        )
        before = copy.deepcopy(session.events)

        messages = session.derive_messages()
        with pytest.raises(TypeError):
            messages[0]["content"][0]["text"] = "HACKED"
        with pytest.raises(TypeError):
            messages[1]["content"][0]["content"].append({"type": "text", "text": "injected"})
        with pytest.raises(TypeError):
            messages[0]["content"].append({"type": "text", "text": "extra"})
        # The returned array is the caller's own snapshot.
        messages.reverse()

        assert session.events == before
        assert session.derive_messages()[0]["content"] == [{"type": "text", "text": "original"}]

    def test_rejects_non_json_serializable_event_data_at_the_source(self):
        session = Session.create(SessionId("s5"))

        def bad(extra):
            return session.append(
                "user/message",
                {"content": [{"type": "text", "text": "x"}], "source": {"kind": "user"}, "extra": extra},
                surface_op="append",
            )

        # The JS scalars `undefined`, `function`, `Symbol`, `Map`, and `Infinity`
        # have no JSON form; Python spells them UNDEFINED, a callable, a set, and
        # an infinite float.
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad(UNDEFINED)
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad(lambda: 0)
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad(set())
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad(float("inf"))
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad([1, object(), 3])
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad({"nested": {"deep": lambda: 0}})
        cyclic = {"a": 1}
        cyclic["self"] = cyclic
        with pytest.raises(ValueError, match="non-JSON-serializable"):
            bad(cyclic)

        assert session.events == []

    def test_rejects_a_surface_eligible_append_with_no_surface_op_marker(self):
        session = Session.create(SessionId("s5b"))
        session.append("turn/start", {"turn": 1})
        with pytest.raises(ValueError, match="surface-eligible and requires a surfaceOp marker"):
            session.append("user/message", _text_message("hi"))
        assert len(session.events) == 1

    def test_accepts_dense_arrays_and_nested_plain_objects(self):
        session = Session.create(SessionId("s6"))
        session.append(
            "user/message",
            {
                "content": [{"type": "text", "text": "x"}],
                "source": {"kind": "user"},
                "extra": [1, 2, [3, {"a": None, "b": True}]],
            },
            surface_op="append",
        )
        assert len(session.events) == 1

    def test_validates_seed_events_rejects_a_non_json_serializable_seed(self):
        bad_seed = [{
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "data": {
                "content": [{"type": "text", "text": "x"}],
                "source": {"kind": "user"},
                "bad": UNDEFINED,
            },
        }]
        with pytest.raises(ValueError, match="losslessly JSON-serializable"):
            Session.create(SessionId("seed-bad"), bad_seed)

    def test_validates_seed_events_rejects_a_non_contiguous_seq(self):
        gap_seed = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {"type": "turn/end", "seq": 5, "time": 2, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        with pytest.raises(ValueError, match=r"contiguous|seq"):
            Session.create(SessionId("seed-gap"), gap_seed)

    def test_validates_seed_events_rejects_a_surface_eligible_event_missing_its_marker(self):
        markerless_seed = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {"type": "user/message", "seq": 1, "time": 2, "data": _text_message("hi")},
            {"type": "turn/end", "seq": 2, "time": 3, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        with pytest.raises(ValueError, match="requires a surfaceOp marker"):
            Session.create(SessionId("seed-no-marker"), markerless_seed)

    def test_accepts_a_well_formed_contiguous_serializable_seed(self):
        good_seed = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {
                "type": "user/message",
                "seq": 1,
                "time": 2,
                "data": _text_message("hi"),
                "surfaceOp": "append",
            },
            {"type": "turn/end", "seq": 2, "time": 3, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        session = Session.create(SessionId("seed-ok"), good_seed)
        assert session.events[:3] == good_seed
        assert session.first_live_seq == 3

    def test_reads_each_seed_array_entry_once_so_validation_and_storage_agree(self):
        accepted = {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}}
        drifted = {"type": "turn/start", "seq": 99, "time": 1, "data": {"turn": 1, "invalid": UNDEFINED}}

        class DriftingSeed:
            """One seed slot that hands out a different event on every read.

            A JavaScript getter can change between the validating read and the
            storing read; this sequence exposes the same hazard for Python
            (`__iter__` is the single read point).
            """

            def __init__(self):
                self.reads = 0

            def __iter__(self):
                self.reads += 1
                yield accepted if self.reads == 1 else drifted

        seed = DriftingSeed()
        session = Session.create(SessionId("seed-entry-snapshot"), seed)

        assert seed.reads == 1
        assert session.events[:1] == [accepted]

    def test_rejects_non_json_surface_metadata_in_a_seed_event(self):
        seed = [{
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "data": _text_message("hello"),
            "surfaceOp": {"op": "replace", "start": UNDEFINED, "end": 2},
        }]
        with pytest.raises(ValueError, match="losslessly JSON-serializable"):
            Session.create(SessionId("seed-bad-metadata"), seed)

    def test_rejects_exotic_seed_metadata_before_cloning_can_erase_its_prototype(self):
        class ReplaceOp:
            op = "replace"
            start = 0
            end = 0

        seed = [{
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "data": _text_message("hello"),
            "surfaceOp": ReplaceOp(),
        }]
        with pytest.raises(ValueError, match="losslessly JSON-serializable"):
            Session.create(SessionId("seed-exotic-metadata"), seed)

    def test_rejects_an_exotic_seed_event_shell_before_spreading_erases_its_prototype(self):
        class SeedEvent:
            type = "turn/start"
            seq = 0
            time = 1
            data = {"turn": 1}

        with pytest.raises(ValueError, match="not losslessly JSON-serializable"):
            Session.create(SessionId("seed-exotic-shell"), [SeedEvent()])

    def test_accepts_a_null_prototype_seed_event_shell_as_a_plain_json_record(self):
        # Python's `dict` is both JavaScript record flavours at once: a plain
        # object and a null-prototype object pass the same strict plain-record
        # check, so this case asserts the accepted half directly.
        event = {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}}
        session = Session.create(SessionId("seed-null-prototype"), [event])
        assert session.events[:1] == [dict(event)]

    def test_adds_seed_context_when_surface_validation_throws_an_error(self, monkeypatch):
        original_validate_next = SurfaceManager.validate_next

        def failing_validate_next(self, event):
            if event.get("seq") == 1:
                raise ValueError("validator failed")
            return original_validate_next(self, event)

        monkeypatch.setattr(SurfaceManager, "validate_next", failing_validate_next)
        seed = [
            {
                "type": "user/message",
                "seq": 0,
                "time": 1,
                "data": _text_message("source"),
                "surfaceOp": "append",
            },
            {
                "type": "user/message",
                "seq": 1,
                "time": 2,
                "data": _text_message("hello"),
                "surfaceOp": {"op": "replace", "start": 0, "end": 0},
                "sourceEventSeqs": [0],
            },
        ]
        with pytest.raises(ValueError, match="invalid seed event at index 1: validator failed"):
            Session.create(SessionId("seed-non-error-metadata-failure"), seed)

    def test_snapshots_the_seed_so_later_mutation_cannot_rewrite_the_log(self):
        seed = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {
                "type": "user/message",
                "seq": 1,
                "time": 2,
                "data": {
                    "id": "seed-input",
                    "role": "user",
                    "content": [{"type": "text", "text": "original"}],
                    "source": {"kind": "user"},
                },
                "surfaceOp": "append",
            },
            {"type": "turn/end", "seq": 2, "time": 3, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        session = Session.create(SessionId("seed-snapshot"), seed)
        seed[1]["data"]["content"][0]["text"] = "HACKED"
        seed[1]["data"]["injected"] = UNDEFINED

        logged = session.events[1]
        assert logged["data"]["content"][0]["text"] == "original"
        assert "injected" not in logged["data"]

    def test_snapshots_append_data_so_later_mutation_cannot_rewrite_the_log(self):
        session = Session.create(SessionId("append-snapshot"))
        data = {
            "id": "append-input",
            "role": "user",
            "content": [{"type": "text", "text": "original"}],
            "source": {"kind": "user"},
        }
        event = session.append("user/message", data, surface_op="append")
        data["content"][0]["text"] = "HACKED"
        data["injected"] = UNDEFINED

        logged = session.events[0]
        assert logged["data"]["content"][0]["text"] == "original"
        assert "injected" not in logged["data"]
        assert event["data"]["content"][0]["text"] == "original"

    def test_rejects_non_json_surface_metadata_before_appending_the_event(self):
        session = Session.create(SessionId("append-bad-metadata"))
        with pytest.raises(ValueError, match="non-JSON-serializable surface metadata"):
            session.append(
                "user/message",
                _text_message("hello"),
                surface_op={"op": "replace", "start": UNDEFINED, "end": 2},
            )
        assert session.events == []

    def test_rejects_exotic_surface_metadata_before_cloning_can_erase_its_prototype(self):
        class ReplaceOp:
            op = "replace"
            start = 0
            end = 0

        session = Session.create(SessionId("append-exotic-metadata"))
        with pytest.raises(ValueError, match="non-JSON-serializable surface metadata"):
            session.append("user/message", _text_message("hello"), surface_op=ReplaceOp())
        assert session.events == []

    def test_rejects_invalid_plain_surface_metadata_shapes_at_append(self):
        session = Session.create(SessionId("append-invalid-surface-shape"))
        data = {"content": [{"type": "text", "text": "hello"}], "source": {"kind": "user"}}

        with pytest.raises(ValueError, match="invalid surfaceOp"):
            session.append("user/message", data, surface_op="invalid")
        with pytest.raises(ValueError, match="invalid replace surfaceOp"):
            session.append("user/message", data, surface_op={"op": "replace", "start": -1, "end": 0})
        with pytest.raises(ValueError, match="non-negative safe integers"):
            session.append("user/message", data, surface_op="append", source_event_seqs=[0, -1])
        assert session.events == []

    def test_rejects_surface_metadata_on_non_surface_append_and_seed_events(self):
        session = Session.create(SessionId("non-surface-metadata"))
        with pytest.raises(ValueError, match="not surface-eligible and cannot carry surfaceOp"):
            session.append("turn/start", {"turn": 1}, surface_op="append")
        with pytest.raises(ValueError, match=r"invalid seed event.*not surface-eligible"):
            Session.create(SessionId("non-surface-metadata-seed"), [{
                "type": "turn/start",
                "seq": 0,
                "time": 1,
                "data": {"turn": 1},
                "surfaceOp": "append",
            }])
        assert session.events == []

    def test_deep_freezes_seeded_and_appended_event_snapshots(self):
        seeded = Session.create(SessionId("seed-frozen"), [{
            "type": "turn/start",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1},
        }])
        seeded_event = seeded.events[0]
        assert _is_frozen(seeded_event)
        assert _is_frozen(seeded_event["data"])
        with pytest.raises(TypeError):
            seeded_event["data"]["turn"] = 99

        appended = Session.create(SessionId("append-frozen"))
        appended_event = appended.append("user/message", _text_message("first"), surface_op="append")
        assert _is_frozen(appended_event)
        assert _is_frozen(appended_event["data"])
        assert _is_frozen(appended_event["data"]["content"])
        assert _is_frozen(appended_event["data"]["content"][0])
        with pytest.raises(TypeError):
            appended_event["data"]["content"][0]["text"] = "mutated"

    def test_iteratively_freezes_deeply_nested_restored_event_data(self):
        depth = 20000
        data = {}
        tail = data
        for _ in range(depth):
            child = {}
            tail["child"] = child
            tail = child
        event = {"type": "test/deep-restore", "seq": 0, "time": 1, "data": data}

        session = Session.from_restore(
            SessionId("deep-restore"),
            [event],
            {"version": SESSION_FORMAT_VERSION, "id": "deep-restore", "createdAt": 1},
        )

        # The reference freezes the borrowed graph in place, so it can measure the
        # chain from the caller's `event`. Python's `deep_freeze` returns fresh
        # frozen containers, so the same chain is measured from the restored log.
        frozen_nodes = 0
        current = session.events[0]
        while isinstance(current, dict):
            if not _is_frozen(current):
                break
            frozen_nodes += 1
            nxt = current.get("data")
            if nxt is None:
                nxt = current.get("child")
            current = nxt
        assert frozen_nodes == depth + 2

    def test_returns_cached_frozen_event_array_snapshots_that_do_not_grow_after_append(self):
        session = Session.create(SessionId("events-snapshot"))
        session.append("turn/start", {"turn": 1})
        before = session.events
        before_event = before[0]

        assert session.events is before
        assert _is_frozen(before)
        with pytest.raises(TypeError):
            before.append(before_event)
        with pytest.raises(TypeError):
            before_event["data"]["turn"] = 99

        session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        after = session.events
        assert len(before) == 1
        assert len(after) == 2
        assert after is not before
        assert session.events is after

    def test_detaches_and_freezes_an_explicitly_supplied_session_header(self):
        source = {
            "version": SESSION_FORMAT_VERSION,
            "id": SessionId("header-owned"),
            "createdAt": 123,
            "cwd": "/accepted",
            "parentSession": SessionId("parent"),
            "seedLength": 2,
        }
        session = Session.create(SessionId("header-owned"), None, source)
        source["cwd"] = "/caller-mutated"

        assert session.header == {
            "version": SESSION_FORMAT_VERSION,
            "id": "header-owned",
            "createdAt": 123,
            "cwd": "/accepted",
            "parentSession": "parent",
            "seedLength": 2,
        }
        assert session.header is not source
        assert session.id == "header-owned"
        assert session.header.cwd == "/accepted"

    def test_rejects_an_exotic_non_json_or_mismatched_supplied_header(self):
        class ExoticHeader:
            version = SESSION_FORMAT_VERSION
            id = SessionId("header-invalid")
            createdAt = 123

        with pytest.raises(ValueError, match="not losslessly JSON-serializable"):
            Session.create(SessionId("header-invalid"), None, ExoticHeader())
        with pytest.raises(ValueError, match="not a plain JSON record"):
            Session.from_restore(SessionId("header-invalid"), [], ExoticHeader())
        for header in [None, 1, []]:
            with pytest.raises(ValueError, match="not a plain JSON record"):
                Session.from_restore(SessionId("header-invalid"), [], header)
        with pytest.raises(ValueError, match="not losslessly JSON-serializable"):
            Session.create(SessionId("header-invalid"), None, {
                "version": SESSION_FORMAT_VERSION,
                "id": SessionId("header-invalid"),
                "createdAt": 123,
                "parentSession": object(),
            })
        with pytest.raises(ValueError, match="does not match session id"):
            Session.create(SessionId("header-invalid"), None, {
                "version": SESSION_FORMAT_VERSION,
                "id": "other",
                "createdAt": 123,
            })

    def test_rejects_invalid_scalar_fields_in_an_explicitly_supplied_header(self):
        base = {
            "version": SESSION_FORMAT_VERSION,
            "id": SessionId("header-shape"),
            "createdAt": 123,
        }
        cases = [
            (1, r"not a plain JSON record"),
            (None, r"not a plain JSON record"),
            (dict(base, version=1), r"header version"),
            (dict(base, createdAt="123"), r"createdAt must be a non-negative safe integer"),
            (dict(base, cwd=1), r"header cwd must be a string"),
            (dict(base, cwd="relative"), r"header cwd must be an absolute path"),
            (dict(base, parentSession=1), r"header parentSession must be a string"),
            (dict(base, seedLength="1"), r"seedLength must be a non-negative safe integer"),
            (dict(base, seedLength=0.5), r"seedLength must be a non-negative safe integer"),
            (dict(base, seedLength=-1), r"seedLength must be a non-negative safe integer"),
        ]
        for header, error in cases:
            with pytest.raises(ValueError, match=error):
                Session.create(SessionId("header-shape"), None, header)

    def test_rejects_seed_records_with_invalid_fixed_envelope_fields(self):
        base = {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}}
        cases = [
            dict(base, extra=True),
            dict(base, type=1),
            dict(base, seq="0"),
            dict(base, seq=0.5),
            dict(base, seq=-1),
            dict(base, time="1"),
            dict(base, time=0.5),
            {"type": base["type"], "seq": base["seq"], "time": base["time"]},
        ]
        for index, event in enumerate(cases):
            with pytest.raises(ValueError, match="invalid event envelope"):
                Session.create(SessionId("bad-envelope-{}".format(index)), [event])


# ============================================================================
# session.spec.ts: SessionStore lifecycle
# ============================================================================

class TestSessionStoreLifecycle:
    def test_creates_sessions_emits_session_created_and_session_event(self):
        ctx, store = _make_store()
        created = []
        events = []
        ctx.on("session/created", lambda session: created.append(session))
        ctx.on("session/event", lambda session, event: events.append((session, event)))

        session = store.create()
        assert created == [session]

        # The store-owned publication hooks are module-private: an unrelated
        # attribute of the old name cannot suppress the durable event feed.
        session.onAppend = None
        session.append("turn/start", {"turn": 1})
        session.append("user/message", _text_message("x"), surface_op="append")
        assert len(events) == 2
        assert events[1][0] is session
        assert events[1][1]["type"] == "user/message"

        assert store.get(session.id) is session
        assert store.list() == [session]

    def test_rejects_duplicate_ids_and_supports_seeding(self):
        ctx, store = _make_store()
        a = store.create(SessionId("fixed"))
        with pytest.raises(ValueError, match="already exists"):
            store.create(SessionId("fixed"))

        a.append("turn/start", {"turn": 1})
        a.append("user/message", _text_message("q"), surface_op="append")
        forked = store.create(SessionId("fork"), {"seed": list(a.events)})
        assert forked.derive_messages() == a.derive_messages()

    def test_enter_rejects_a_stale_prepared_session_whose_id_is_already_live(self):
        ctx, store = _make_store()
        stale = store.prepare(SessionId("racy"))
        live = store.create(SessionId("racy"))
        with pytest.raises(ValueError, match="already exists"):
            store.enter(stale)
        assert store.get(SessionId("racy")) is live

    def test_prepare_enter_and_announce_register_a_session_and_emit_session_created(self):
        ctx, store = _make_store()
        created = []
        ctx.on("session/created", lambda session: created.append(session))

        session = store.prepare(SessionId("lifecycle"))
        # prepare alone does NOT enter the store.
        assert store.get(SessionId("lifecycle")) is None
        detach = store.enter(session)
        assert store.get(SessionId("lifecycle")) is session
        # enter does NOT announce.
        assert created == []
        store.announce(session)
        assert created == [session]
        # The detach disposer removes the entry; it is idempotent.
        detach()
        detach()
        assert store.get(SessionId("lifecycle")) is None

    def test_prevents_simultaneous_attachment_of_one_session_object_to_two_stores(self):
        first_ctx, first = _make_store()
        second_ctx, second = _make_store()
        session = Session.create(SessionId("owned-key"))
        detach_first = first.enter(session)

        with pytest.raises(ValueError, match="already attached to a store"):
            second.enter(session)
        assert first.get(SessionId("owned-key")) is session

        detach_first()
        assert first.get(SessionId("owned-key")) is None
        detach_second = second.enter(session)
        assert second.get(SessionId("owned-key")) is session
        detach_second()

    def test_rejects_direct_and_reentrant_repeat_announcements(self):
        ctx, store = _make_store()
        counters = {"created": 0, "disposed": 0}
        state = {"reentrant_error": ""}

        def on_created(session):
            counters["created"] += 1
            try:
                store.announce(session)
            except Exception as error:
                state["reentrant_error"] = str(error)

        ctx.on("session/created", on_created)
        ctx.on("session/disposed", lambda session: counters.__setitem__("disposed", counters["disposed"] + 1))

        session = store.prepare(SessionId("once"))
        detach = store.enter(session)
        store.announce(session)
        assert re.search("already announced", state["reentrant_error"])
        with pytest.raises(RuntimeError, match="already announced"):
            store.announce(session)
        detach()
        assert counters == {"created": 1, "disposed": 1}

    def test_defers_a_reentrant_detach_until_the_creation_dispatch_unwinds(self):
        ctx, store = _make_store()
        order = []
        session = store.prepare(SessionId("reentrant-detach"))
        detach = store.enter(session)

        def on_created_first(created):
            order.append("created:first")
            detach()
            assert store.get(created.id) is created

        def on_created_second(created):
            order.append("created:second")
            assert store.get(created.id) is created

        def on_disposed(disposed):
            order.append("disposed")
            assert store.get(disposed.id) is None

        ctx.on("session/created", on_created_first)
        ctx.on("session/created", on_created_second)
        ctx.on("session/disposed", on_disposed)

        store.announce(session)

        assert order == ["created:first", "created:second", "disposed"]
        assert store.get(session.id) is None
        detach()

    @pytest.mark.asyncio
    async def test_rolls_back_create_when_its_owner_unloads_from_session_created(self):
        ctx, store = _make_store()

        class OwnerPlugin(Plugin):
            id = "create-unload-owner"
            name = "create-unload-owner"
            inject = ["sessions"]

            def apply(self, inner):
                self.inner = inner

        owner = OwnerPlugin()
        fiber = await ctx.plugin(owner)
        pending = []

        def on_created(session):
            if session.id == "create-unload-race":
                # The reference is fire-and-forget (`void owner.dispose()`);
                # Python schedules the same disposal on the running loop.
                pending.append(asyncio.ensure_future(fiber.dispose()))

        ctx.on("session/created", on_created)
        owner.inner.sessions.create(SessionId("create-unload-race"))
        for task in pending:
            await task
        await fiber.dispose()
        assert store.get(SessionId("create-unload-race")) is None

    def test_synthesizes_a_minimal_current_version_header_for_a_bare_created_session(self):
        ctx, store = _make_store()
        session = store.create(SessionId("plain"))
        assert session.header.version == SESSION_FORMAT_VERSION
        assert session.header.id == "plain"
        assert isinstance(session.header.createdAt, int)
        assert session.header.cwd is None
        assert session.header.parentSession is None

    def test_attaches_cwd_and_parent_session_from_meta_to_the_header(self):
        ctx, store = _make_store()
        session = store.create(SessionId("child"), {
            "meta": {"cwd": "/work/project", "parentSession": SessionId("parent")},
        })
        assert session.header.version == SESSION_FORMAT_VERSION
        assert session.header.id == "child"
        assert session.header.cwd == "/work/project"
        assert session.header.parentSession == "parent"

    def test_attaches_subagent_origin_and_delegation_depth_from_meta_to_the_header(self):
        ctx, store = _make_store()
        session = store.create(SessionId("delegated-child"), {
            "meta": {"parentSession": SessionId("parent"), "origin": "subagent", "delegationDepth": 2},
        })
        assert session.header.id == "delegated-child"
        assert session.header.parentSession == "parent"
        assert session.header.origin == "subagent"
        assert session.header.delegationDepth == 2

    def test_rejects_non_json_and_invalid_scalar_session_metadata(self):
        ctx, store = _make_store()
        cases = [
            ({"parentSession": UNDEFINED}, r"header is not losslessly JSON-serializable"),
            ({"cwd": 1}, r"header cwd must be a string"),
            ({"parentSession": 1}, r"header parentSession must be a string"),
            ({"createdAt": "123"}, r"header createdAt must be a non-negative safe integer"),
            ({"createdAt": 1.5}, r"header createdAt must be a non-negative safe integer"),
            ({"createdAt": -1}, r"header createdAt must be a non-negative safe integer"),
            ({"createdAt": 9007199254740992}, r"header createdAt must be a non-negative safe integer"),
            ({"seedLength": "1"}, r"seedLength must be a non-negative safe integer"),
            ({"seedLength": 0.5}, r"seedLength must be a non-negative safe integer"),
            ({"seedLength": -1}, r"seedLength must be a non-negative safe integer"),
            ({"origin": "fork"}, r'origin must be "subagent"'),
            ({"delegationDepth": "1"}, r"delegationDepth must be a non-negative safe integer"),
            ({"delegationDepth": 0.5}, r"delegationDepth must be a non-negative safe integer"),
            ({"delegationDepth": -1}, r"delegationDepth must be a non-negative safe integer"),
            ({"agentPreset": 1}, r"agentPreset must be a string"),
        ]
        for index, (meta, error) in enumerate(cases):
            with pytest.raises(ValueError, match=error):
                store.prepare(SessionId("bad-meta-{}".format(index)), {"meta": meta})

    def test_rejects_a_non_absolute_meta_cwd(self):
        ctx, store = _make_store()
        with pytest.raises(ValueError, match="cwd must be an absolute path"):
            store.create(SessionId("rel"), {"meta": {"cwd": "relative/path"}})
        assert store.get(SessionId("rel")) is None

    def test_a_bare_session_constructed_without_the_store_still_exposes_a_current_version_header(self):
        session = Session.create(SessionId("bare"))
        assert session.header.version == SESSION_FORMAT_VERSION
        assert session.header.id == "bare"
        assert isinstance(session.header.createdAt, int)

    @pytest.mark.asyncio
    async def test_detaches_sessions_when_the_creating_fiber_is_disposed(self):
        ctx, store = _make_store()

        class ScopedOwnerPlugin(Plugin):
            id = "scoped-owner"
            name = "scoped-owner"
            inject = ["sessions"]

            def apply(self, inner):
                self.session = inner.sessions.create(SessionId("scoped"))

        owner = ScopedOwnerPlugin()
        fiber = await ctx.plugin(owner)
        assert store.get(SessionId("scoped")) is owner.session

        observed = []
        ctx.on("session/event", lambda session, event: observed.append(event))

        await fiber.dispose()
        assert store.get(SessionId("scoped")) is None
        owner.session.append("user/message", _text_message("late"), surface_op="append")
        assert observed == []

    def test_pairs_a_partial_session_created_announcement_with_disposal_during_rollback(self):
        ctx, store = _make_store()
        state = {"threw": False}
        disposed = []
        ctx.on("session/disposed", lambda session: disposed.append(session))

        def on_created(session):
            if not state["threw"]:
                state["threw"] = True
                raise ValueError("boom created listener")

        ctx.on("session/created", on_created)

        with pytest.raises(ValueError, match="boom created listener"):
            store.create(SessionId("fixed"))
        assert store.get(SessionId("fixed")) is None
        assert [session.id for session in disposed] == ["fixed"]

        events = []
        ctx.on("session/event", lambda session, event: events.append(event))
        session = store.create(SessionId("fixed"))
        assert store.get(SessionId("fixed")) is session
        session.append("turn/start", {"turn": 1})
        session.append("user/message", _text_message("hi"), surface_op="append")
        assert events[-1]["type"] == "user/message"


# ============================================================================
# session.spec.ts: dispatch resolution and observer containment
# ============================================================================

class TestSessionDispatchAndObservers:
    @pytest.mark.asyncio
    async def test_contains_session_event_observer_failures_after_the_append_commit_point(self):
        ctx, store = _make_store()
        warnings = []
        ctx.logger.warn = lambda message, *args: warnings.append(str(message))
        session = store.create(SessionId("contained-event"))
        heard = []
        committed_before_notify = []

        def sync_observer(observed_session, event):
            committed_before_notify.append(observed_session.events[-1] is event)
            raise ValueError("sync event observer")

        async def async_observer(_observed_session, _event):
            raise ValueError("async event observer")

        ctx.on("session/event", sync_observer)
        ctx.on("session/event", async_observer)
        ctx.on("session/event", lambda _observed_session, event: heard.append(event))

        appended = session.append("turn/start", {"turn": 1})
        assert committed_before_notify == [True]
        assert session.events == [appended]
        assert heard == [appended]

        for _ in range(5):
            await asyncio.sleep(0)

        # JavaScript renders a listener failure through `String(error)`, which
        # prefixes the constructor name; Python's `str(exception)` does not
        # (LEGAL_ADAPTATION).
        assert warnings == [
            'session "contained-event": session/event listener threw: sync event observer',
            'session "contained-event": session/event listener rejected: async event observer',
        ]

    def test_runs_internal_dispatch_validation_on_one_frozen_candidate_before_commit(self):
        ctx, store = _make_store()
        session = store.create(SessionId("dispatch-veto"))
        validations = []
        observed = []
        state = {"reject": True}

        def on_dispatch(mode, name, args, caller):
            if name != "session/event":
                return
            observed_session, event = args[0], args[1]
            validations.append({
                "event": event,
                "log_length": len(observed_session.events),
                "frozen": _is_frozen(event) and _is_frozen(event["data"]),
            })
            if state["reject"]:
                state["reject"] = False
                raise ValueError("reject first candidate")

        ctx.on("internal/dispatch", on_dispatch)
        ctx.on("session/event", lambda _observed_session, event: observed.append(event))

        with pytest.raises(ValueError, match="reject first candidate"):
            session.append("turn/start", {"turn": 1})
        assert session.events == []
        assert observed == []

        appended = session.append("turn/start", {"turn": 1})
        assert [(v["log_length"], v["frozen"]) for v in validations] == [(0, True), (0, True)]
        assert [v["event"]["seq"] for v in validations] == [0, 0]
        assert validations[1]["event"] is appended
        assert session.events == [appended]
        assert observed == [appended]

    def test_does_not_publish_a_surface_transition_rejected_by_internal_dispatch(self):
        ctx, store = _make_store()
        session = store.create(SessionId("surface-dispatch-veto"))
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})
        session.append("user/message", _text_message("source"), surface_op="append")
        surface = session.surface
        state = {"reject": True}

        def on_dispatch(mode, name, args, caller):
            if name == "session/event" and state["reject"]:
                state["reject"] = False
                raise ValueError("reject surface candidate")

        ctx.on("internal/dispatch", on_dispatch)

        with pytest.raises(ValueError, match="reject surface candidate"):
            session.append(
                "assistant/message",
                {"turn": 1, "step": 1, "message": _assistant_message("replacement")},
                surface_op={"op": "replace", "start": 2, "end": 2},
                source_event_seqs=[2],
            )

        assert len(session.events) == 3
        assert surface.nodes == [2]
        assert surface.replace_generation == 0

        session.append("user/message", _text_message("next"), surface_op="append")
        assert surface.nodes == [2, 3]
        assert surface.replace_generation == 0

    def test_resolves_session_event_dispatch_before_commit_so_instrumentation_cannot_hide_it(self):
        ctx, store = _make_store()
        session = store.create(SessionId("dispatch-check"))
        observed = []

        def on_dispatch(mode, name, args, caller):
            if name == "session/event":
                raise ValueError("dispatch instrumentation rejected the carrier")

        ctx.on("internal/dispatch", on_dispatch)
        ctx.on("session/event", lambda _observed_session, event: observed.append(event))

        with pytest.raises(ValueError, match="dispatch instrumentation rejected the carrier"):
            session.append("turn/start", {"turn": 1})
        assert session.events == []
        assert observed == []

    def test_defers_detach_through_dispatch_resolution_commit_and_observer_publication(self):
        ctx, store = _make_store()
        order = []
        session = store.prepare(SessionId("detach-during-append"))
        detach = store.enter(session)

        def on_dispatch(mode, name, args, caller):
            if name != "session/event":
                return
            observed_session = args[0]
            order.append("resolve:" + ("live" if store.get(observed_session.id) is observed_session else "detached"))
            detach()

        ctx.on("internal/dispatch", on_dispatch)
        ctx.on(
            "session/event",
            lambda observed_session, _event: order.append(
                "observe:" + ("live" if store.get(observed_session.id) is observed_session else "detached")
            ),
        )
        ctx.on(
            "session/disposed",
            lambda disposed: order.append(
                "dispose:" + ("live" if store.get(disposed.id) is disposed else "detached")
            ),
        )
        store.announce(session)

        appended = session.append("turn/start", {"turn": 1})

        assert session.events == [appended]
        assert order == ["resolve:live", "observe:live", "dispose:detached"]
        assert store.get(session.id) is None

    @pytest.mark.asyncio
    async def test_observes_async_session_created_rejection_without_rolling_back_or_starving_peers(self):
        ctx, store = _make_store()
        warnings = []
        ctx.logger.warn = lambda message, *args: warnings.append(str(message))
        heard = []

        async def late_failure(_session):
            raise ValueError("late creation failure")

        ctx.on("session/created", late_failure)
        ctx.on("session/created", lambda session: heard.append(session.id))

        session = store.create(SessionId("async-created"))
        for _ in range(5):
            await asyncio.sleep(0)

        assert store.get(session.id) is session
        assert heard == ["async-created"]
        assert warnings == [
            'session "async-created": session/created listener rejected: late creation failure',
        ]

    @pytest.mark.asyncio
    async def test_contains_synchronous_and_async_session_disposed_listener_failures_per_observer(self):
        ctx, store = _make_store()
        warnings = []
        ctx.logger.warn = lambda message, *args: warnings.append(str(message))
        heard = []

        def sync_disposed(_session):
            raise ValueError("sync disposed")

        async def async_disposed(_session):
            raise ValueError("async disposed")

        ctx.on("session/disposed", sync_disposed)
        ctx.on("session/disposed", async_disposed)
        ctx.on("session/disposed", lambda session: heard.append(session.id))

        unannounced = store.prepare(SessionId("never-announced"))
        detach_unannounced = store.enter(unannounced)
        detach_unannounced()
        assert heard == []

        announced = store.prepare(SessionId("contained-disposal"))
        detach = store.enter(announced)
        store.announce(announced)
        detach()
        for _ in range(5):
            await asyncio.sleep(0)

        assert heard == ["contained-disposal"]
        assert warnings == [
            'session "contained-disposal": session/disposed listener threw: sync disposed',
            'session "contained-disposal": session/disposed listener rejected: async disposed',
        ]

    def test_contains_internal_dispatch_failure_after_session_detachment(self):
        ctx, store = _make_store()
        warnings = []
        ctx.logger.warn = lambda message, *args: warnings.append(str(message))
        heard = []

        def on_dispatch(mode, name, args, caller):
            if name == "session/disposed":
                raise ValueError("disposed dispatch instrumentation")

        ctx.on("internal/dispatch", on_dispatch)
        ctx.on("session/disposed", lambda session: heard.append(session))
        session = store.prepare(SessionId("disposed-dispatch"))
        detach = store.enter(session)
        store.announce(session)

        detach()
        assert store.get(session.id) is None
        assert heard == []
        assert warnings == [
            'session "disposed-dispatch": session/disposed dispatch threw: disposed dispatch instrumentation',
        ]

    def test_does_not_let_internal_dispatch_replace_the_disposed_callback_tuple(self):
        ctx, store = _make_store()
        replacement = Session.create(SessionId("replacement-disposed"))
        heard = []

        def on_dispatch(mode, name, args, caller):
            if name == "session/disposed":
                args[0] = replacement

        ctx.on("internal/dispatch", on_dispatch)
        ctx.on("session/disposed", lambda session: heard.append(session))
        session = store.prepare(SessionId("fixed-disposed-tuple"))
        detach = store.enter(session)
        store.announce(session)

        detach()

        assert heard == [session]


class TestReferenceValidationOrderAndAdoptionBounds:
    """Pins the reference validation ORDER and admission bounds that no single
    upstream case isolates: `assertMessageEventShape` runs the shared content
    check before the assistant model-source check (index.ts:324-331) and reads
    only `data.message` for a non-user message (index.ts:307); `adoptSessionEvent`
    admits an event on its message shape alone (index.ts:167-185), and
    `snapshotSessionEvent` is exactly `structuredClone` + adopt (index.ts:192-194)
    with no envelope or request-header vocabulary check."""

    def test_reports_invalid_assistant_content_before_the_model_source(self):
        seed = [{
            "type": "assistant/message", "seq": 0, "time": 1, "surfaceOp": "append",
            "data": {
                "turn": 1, "step": 1,
                "message": {
                    "id": "double-defect",
                    "role": "assistant",
                    "content": "not-an-array",
                    "source": {"kind": "user"},
                },
            },
        }]
        with pytest.raises(ValueError, match="message has invalid content"):
            Session.create(SessionId("assistant-content-first"), seed)

    def test_rejects_an_assistant_seed_without_a_nested_message_record(self):
        seed = [{
            "type": "assistant/message", "seq": 0, "time": 1, "surfaceOp": "append",
            "data": {
                "turn": 1, "step": 1,
                "id": "not-nested",
                "role": "assistant",
                "content": [],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            },
        }]
        with pytest.raises(ValueError, match=r"lacks an identified message"):
            Session.create(SessionId("assistant-no-message"), seed)

    def test_adopts_a_message_event_whose_envelope_carries_unknown_keys(self):
        event = {
            "type": "user/message", "seq": 0, "time": 1, "surfaceOp": "append", "extra": 1,
            "data": {
                "id": "owned-extra",
                "role": "user",
                "content": [{"type": "text", "text": "owned"}],
                "source": {"kind": "user"},
            },
        }
        # The message shape is the only admission check: an unknown envelope key is
        # preserved, not rejected.
        assert adopt_session_event(event) is event
        assert event["extra"] == 1

    def test_snapshots_a_log_only_event_without_re_validating_its_envelope(self):
        event = {"type": "session/end-seed", "seq": 0, "time": 1, "data": {}, "extra": True}
        snapshot = snapshot_session_event(event)
        assert snapshot == event
        assert snapshot is not event

    def test_snapshots_a_legacy_request_header_delta_without_the_seed_vocabulary_check(self):
        event = {"type": "request/header-delta", "seq": 0, "time": 1, "data": {"config": {}}}
        snapshot = snapshot_session_event(event)
        assert snapshot == event
