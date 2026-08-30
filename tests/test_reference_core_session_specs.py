"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session
Covers:
- chunk-rows codec (text, reasoning, tool call, error checking, limits)
- derived-cache (growth, surface replacement, fresh arrays, per-event projection)
- fork (lineage, boundaries, balance, open-turn rejection, error codes)
- json (scalar vocabulary, snapshot, deepcopy invariants)
- request-header (canonicalization, equality, snapshot folding, format rejection)
- seq-ranges (encoding, decoding, boundary checks)
"""

import json
import math
import os
import pytest
from dsh.cordis.context import Context
from dsh.core.session import (
    Session,
    SessionForkError,
    SessionHeader,
    SessionStore,
    canonical_header,
    fold_request_header,
    header_equals,
    snapshot_json_value,
    validate_session_header,
)
from dsh.session.chunk_rows import (
    chunk_row_length,
    decode_storage_record,
    is_chunk_row,
    pack_chunk_runs,
)
from dsh.session.seq_ranges import decode_seq_ranges, encode_seq_ranges


# ============================================================================
# 1. seq-ranges 1:1 parity (from session/tests/seq-ranges.spec.ts)
# ============================================================================

def test_seq_ranges_round_trip():
    test_cases = [
        [],
        [5],
        [10, 11, 12, 13, 14],
        [16, 17, 100, 200, 201, 202, 203],
        [3, 2],
        [9007199254740990, 0, 9007199254740989],
    ]
    for values in test_cases:
        encoded = encode_seq_ranges(values)
        decoded = decode_seq_ranges(encoded)
        assert decoded == values


def test_seq_ranges_encodes_profitable_increasing_runs():
    assert encode_seq_ranges([1, 3, 4, 5, 7]) == [1, [3, 5], 7]
    assert encode_seq_ranges([1, 3, 4, 7]) == [1, 3, 4, 7]
    assert encode_seq_ranges([3, 2]) == [3, 2]


def test_seq_ranges_large_array_provenance():
    values = list(range(100_001))
    assert encode_seq_ranges(values) == [[0, 100_000]]


def test_seq_ranges_rejects_malformed():
    with pytest.raises(TypeError, match="must be an array"):
        decode_seq_ranges("nope")
    with pytest.raises(TypeError, match="non-negative safe integers"):
        decode_seq_ranges([-1])
    with pytest.raises(TypeError, match="range entries must be"):
        decode_seq_ranges([[1]])
    with pytest.raises(TypeError, match="start <= end"):
        decode_seq_ranges([[4, 2]])
    with pytest.raises(TypeError, match="strictly increasing"):
        decode_seq_ranges([[2, 5], [4, 7]])
    with pytest.raises(TypeError, match="exceeds its event sequence"):
        decode_seq_ranges([0], max_entries=0)
    with pytest.raises(TypeError, match="exceeds its event sequence"):
        decode_seq_ranges([[0, 10]], max_entries=10)


# ============================================================================
# 2. request-header 1:1 parity (from session/tests/request-header.spec.ts)
# ============================================================================

def test_canonical_header_normalizes_empty_fields():
    config = {"provider": "mock", "model": "m"}
    assert canonical_header({
        "config": config,
        "adapterDefaults": {},
        "system": "",
        "tools": [],
    }) == {"config": config}

    full = canonical_header({
        "config": {**config, "maxTokens": 256_000},
        "adapterDefaults": {"maxTokens": True},
        "system": "s",
        "tools": [{"name": "a", "description": "d", "parameters": {"type": "object"}}],
    })
    assert full == {
        "config": {**config, "maxTokens": 256_000},
        "adapterDefaults": {"maxTokens": True},
        "system": "s",
        "tools": [{"name": "a", "description": "d", "parameters": {"type": "object"}}],
    }


def test_header_equals_comparison():
    config = {"provider": "mock", "model": "m"}
    base = canonical_header({
        "config": config,
        "system": "s",
        "tools": [{"name": "a", "description": "d", "parameters": {"type": "object"}}],
    })

    assert header_equals(base, dict(base)) is True
    assert header_equals(base, {**base, "config": {"provider": "mock", "model": "other"}}) is False
    assert header_equals(base, {**base, "system": "other"}) is False
    assert header_equals(base, {**base, "tools": []}) is False
    assert header_equals({"config": config}, {"config": config, "tools": []}) is True


def test_fold_request_header():
    config = {"provider": "mock", "model": "m"}
    session = Session(session_id="fold-hdr")
    session.append("turn/start", {"turn": 1})
    session.append("request/header", {"header": {"config": config, "system": "first"}, "reason": "initial"})
    session.append_user_message("hi")
    session.append("request/header", {"header": {"config": {"provider": "mock", "model": "other"}, "tools": []}, "reason": "change"})

    assert fold_request_header(session.events) == {"config": {"provider": "mock", "model": "other"}}


def test_legacy_request_header_delta_rejection():
    legacy = [{"type": "request/header-delta", "seq": 0, "time": 1, "data": {"config": {"provider": "mock"}}}]
    with pytest.raises(ValueError, match="unsupported legacy request/header-delta"):
        Session(session_id="legacy-seed", seed=legacy)

    session = Session(session_id="legacy-append")
    with pytest.raises(ValueError, match="unsupported legacy request/header-delta"):
        session.append("request/header-delta", {"config": {}})


# ============================================================================
# 3. derived-cache 1:1 parity (from session/tests/derived-cache.spec.ts)
# ============================================================================

def test_derived_messages_incremental_caching_and_growth():
    session = Session(session_id="cache-grow")
    session.append("turn/start", {"turn": 1})
    session.append_user_message("one")

    scratch1 = Session.create("scratch-1", seed=session.events).derive_messages()
    assert session.derive_messages() == scratch1

    session.append_user_message("two")
    session.append_assistant_message({
        "role": "assistant",
        "content": [{"type": "text", "text": "reply"}],
    }, turn=1, step=1)

    scratch2 = Session.create("scratch-2", seed=session.events).derive_messages()
    assert session.derive_messages() == scratch2

    # Usage-only assistant step (content empty) produces no message
    session.append_assistant_message({
        "role": "assistant",
        "content": [],
    }, turn=1, step=2, usage={"inputTokens": 1, "outputTokens": 0})

    scratch3 = Session.create("scratch-3", seed=session.events).derive_messages()
    assert session.derive_messages() == scratch3


def test_derived_messages_surface_replacement_rebuild():
    session = Session(session_id="cache-replace")
    session.append("turn/start", {"turn": 1})
    session.append_user_message("one")
    session.append_user_message("two")

    before_replace = session.derive_messages()
    assert len(before_replace) == 2

    nodes = session.surface.nodes
    session.append_user_message(
        "summary",
        surface_op={"op": "replace", "start": nodes[0], "end": nodes[1]},
        source_event_seqs=[nodes[0], nodes[1]],
    )

    after_replace = session.derive_messages()
    assert len(after_replace) == 1
    assert len(before_replace) == 2  # previous array snapshot unchanged
    assert after_replace == Session.create("scratch-repl", seed=session.events).derive_messages()


def test_derived_event_message_projection():
    session = Session(session_id="per-event")
    session.append("turn/start", {"turn": 1})
    event = session.append_user_message("hi")
    derived_single = session.derive_event_message(event)
    derived_full = session.derive_messages()[-1]
    assert derived_single == derived_full

    boundary = session.append("step/start", {"turn": 1, "step": 1})
    assert session.derive_event_message(boundary) is None

    empty = session.append_assistant_message({"role": "assistant", "content": []})
    assert session.derive_event_message(empty) is None


# ============================================================================
# 4. fork 1:1 parity (from session/tests/fork.spec.ts)
# ============================================================================

def test_session_store_fork_empty_and_default_boundary():
    store = SessionStore()
    source = store.create("empty-parent", meta={"cwd": os.path.abspath(".")})
    child = store.fork(source, child_session_id="empty-child")

    assert child.id == "empty-child"
    assert child.header.parent_session == "empty-parent"
    assert child.header.seed_length == 0
    assert len(child.events) >= 1  # end-seed marker


def test_session_store_fork_completed_turn():
    store = SessionStore()
    source = store.create("parent", meta={"cwd": os.path.abspath(".")})
    source.append("turn/start", {"turn": 1})
    source.append_user_message("hello")
    source.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    child = store.fork("parent", child_session_id="child")
    assert child.header.parent_session == "parent"
    assert child.header.seed_length == len(source.events)
    assert child.events[0]["type"] == "turn/start"


def test_session_store_fork_rejects_open_turn():
    store = SessionStore()
    source = store.create("open-parent")
    source.append("turn/start", {"turn": 1})
    source.append_user_message("open")

    with pytest.raises(SessionForkError) as exc:
        store.fork(source, boundary=1)
    assert exc.value.code == "OPEN_TURN"


def test_session_store_fork_rejects_duplicate_child_id():
    store = SessionStore()
    source = store.create("parent-dup")
    source.append("turn/start", {"turn": 1})
    source.append_user_message("hello")
    source.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    store.create("child-dup")
    with pytest.raises(SessionForkError) as exc:
        store.fork(source, child_session_id="child-dup")
    assert exc.value.code == "SESSION_ALREADY_EXISTS"


def test_session_store_fork_rejects_nonexistent_or_stale():
    store = SessionStore()
    with pytest.raises(SessionForkError) as exc1:
        store.fork("missing-session")
    assert exc1.value.code == "SESSION_NOT_FOUND"

    detached = Session(session_id="detached")
    with pytest.raises(SessionForkError) as exc2:
        store.fork(detached)
    assert exc2.value.code == "SESSION_NOT_FOUND"


# ============================================================================
# 5. json snapshot 1:1 parity (from session/tests/json.spec.ts)
# ============================================================================

def test_snapshot_json_value_scalars_and_containers():
    assert snapshot_json_value(None) is None
    assert snapshot_json_value(True) is True
    assert snapshot_json_value("text") == "text"
    assert snapshot_json_value(1.25) == 1.25
    assert snapshot_json_value({"a": [1, 2, {"b": "c"}]}) == {"a": [1, 2, {"b": "c"}]}

    # Unsupported objects return None
    assert snapshot_json_value(lambda x: x) is None
    assert snapshot_json_value(object()) is None


# ============================================================================
# 6. session 1:1 full invariant & validation suite (from session/tests/session.spec.ts)
# ============================================================================

def test_session_derives_message_history_and_omits_raw_chunks():
    session = Session.create("s1")
    session.append("turn/start", {"turn": 1})
    session.append("user/message", {
        "id": "u1",
        "role": "user",
        "content": [{"type": "text", "text": "hello"}],
        "source": {"kind": "user"},
    }, surface_op="append")
    session.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "hi"}})
    session.append("assistant/message", {
        "turn": 1,
        "step": 1,
        "message": {
            "id": "a1",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "let me check"},
                {"type": "tool-call", "id": "c1", "name": "echo", "arguments": "{}"},
            ],
            "source": {"kind": "model", "provider": "mock", "model": "mock"},
        },
    }, surface_op="append")
    session.append("tool/result", {
        "turn": 1,
        "step": 1,
        "message": {
            "id": "t1",
            "role": "user",
            "content": [{"type": "tool-result", "toolCallId": "c1", "content": [{"type": "text", "text": "ok"}]}],
            "source": {"kind": "tool", "callId": "c1"},
        },
    }, surface_op="append")
    session.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})

    messages = session.derive_messages()
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert len(messages[1]["content"]) == 2
    assert messages[2]["content"][0]["type"] == "tool-result"
    assert messages[2]["content"][0]["toolCallId"] == "c1"


def test_session_round_trips_max_tokens_and_aborted_reasons():
    session = Session.create("s-reasons")
    session.append("turn/start", {"turn": 1})
    session.append("turn/end", {"turn": 1, "reason": {"kind": "max-tokens"}})
    assert session.events[-1]["data"]["reason"] == {"kind": "max-tokens"}

    session2 = Session.create("s-abort")
    session2.append("turn/start", {"turn": 1})
    session2.append("turn/end", {"turn": 1, "reason": {"kind": "aborted", "reason": {"kind": "user"}}})
    replayed = Session.create("s-abort-replay", seed=session2.events)
    turn_end = [e for e in replayed.events if e.get("type") == "turn/end"][-1]
    assert turn_end["data"]["reason"] == {"kind": "aborted", "reason": {"kind": "user"}}


def test_session_rejects_missing_provider_model_and_malformed_messages():
    bad_header = {"type": "request/header", "seq": 0, "time": 1, "data": {"header": {"config": {"model": "m"}}, "reason": "initial"}}
    with pytest.raises(ValueError, match="lacks provider/model"):
        Session.create("bad-hdr", seed=[bad_header])

    bad_assistant = {
        "type": "assistant/message", "seq": 0, "time": 1, "surfaceOp": "append",
        "data": {"turn": 1, "step": 1, "content": [{"type": "text", "text": "old"}]},
    }
    with pytest.raises(ValueError, match="lacks an identified message"):
        Session.create("bad-asst", seed=[bad_assistant])

    user_base = {"id": "u", "role": "user", "content": [{"type": "text", "text": "c"}], "source": {"kind": "user"}}

    # Wrong role
    with pytest.raises(ValueError, match='message must have role "user"'):
        Session.create("bad-role", seed=[{"type": "user/message", "seq": 0, "time": 1, "surfaceOp": "append", "data": {**user_base, "role": "assistant"}}])

    # Invalid source
    with pytest.raises(ValueError, match="message has invalid source"):
        Session.create("bad-src", seed=[{"type": "user/message", "seq": 0, "time": 1, "surfaceOp": "append", "data": {**user_base, "source": None}}])

    # Non-array content
    with pytest.raises(ValueError, match="message has invalid content"):
        Session.create("bad-content", seed=[{"type": "user/message", "seq": 0, "time": 1, "surfaceOp": "append", "data": {**user_base, "content": "not-array"}}])


def test_session_reasoning_effort_and_adapter_defaults_validation():
    valid_header = {
        "type": "request/header", "seq": 0, "time": 1,
        "data": {
            "header": {
                "config": {"provider": "mock", "model": "m", "reasoningEffort": "high", "maxTokens": 1000},
                "adapterDefaults": {"maxTokens": True},
            },
            "reason": "initial",
        },
    }
    sess = Session.create("val-hdr", seed=[valid_header])
    assert sess.events[0]["data"]["header"]["config"]["reasoningEffort"] == "high"

    # Invalid empty reasoning effort
    invalid_effort = json.loads(json.dumps(valid_header))
    invalid_effort["data"]["header"]["config"]["reasoningEffort"] = ""
    with pytest.raises(ValueError, match="has an invalid reasoningEffort"):
        Session.create("inv-effort", seed=[invalid_effort])

    # Invalid adapter defaults
    invalid_defaults = json.loads(json.dumps(valid_header))
    invalid_defaults["data"]["header"]["adapterDefaults"] = {"unknown": True}
    with pytest.raises(ValueError, match="has invalid adapterDefaults"):
        Session.create("inv-defaults", seed=[invalid_defaults])


def test_session_rejects_non_json_data_at_source():
    session = Session.create("s-json-check")
    with pytest.raises(TypeError, match="not losslessly JSON-serializable"):
        session.append("turn/start", {"bad": lambda x: x})

    with pytest.raises(TypeError, match="not losslessly JSON-serializable"):
        session.append("turn/start", {"bad": float("inf")})

    assert len(session.events) == 0


def test_session_rejects_non_contiguous_seed():
    gap_seed = [
        {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
        {"type": "turn/end", "seq": 5, "time": 2, "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]
    with pytest.raises(ValueError, match="seed must be contiguous from 0"):
        Session.create("gap-seed", seed=gap_seed)


def test_session_log_isolated_from_mutation_through_derived_messages():
    session = Session.create("isolation")
    session.append_user_message("original")
    before = json.loads(json.dumps(session.events))

    messages = session.derive_messages()
    messages[0]["content"][0]["text"] = "HACKED"

    # Log remains unchanged
    assert session.events == before
    fresh = session.derive_messages()
    assert fresh[0]["content"][0]["text"] == "original"


def test_session_store_lifecycle_and_rollback_on_listener_error():
    ctx = Context()
    store = SessionStore(ctx=ctx)
    ctx.set_service("sessions", store)

    lifecycle = []
    ctx.on("session/created", lambda s: lifecycle.append(f"created:{s.id}"))
    ctx.on("session/disposed", lambda s: lifecycle.append(f"disposed:{s.id}"))

    s1 = store.create("s-life")
    assert store.get("s-life") == s1
    assert store.list() == [s1]

    # Listener throw triggers rollback and cleanup
    def veto(s):
        if s.id == "s-veto":
            raise ValueError("session creation vetoed")

    ctx.on("session/created", veto)

    with pytest.raises(ValueError, match="session creation vetoed"):
        store.create("s-veto")

    assert store.get("s-veto") is None
    assert "created:s-veto" in lifecycle
    assert "disposed:s-veto" in lifecycle

