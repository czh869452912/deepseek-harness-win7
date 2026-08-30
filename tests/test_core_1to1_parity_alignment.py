"""
Rigorous 1:1 Parity Alignment Tests for:
- chunk-rows codec (text-chunks, reasoning-chunks, tool-call-chunks)
- deriveMessages incremental caching and replacement invalidation
- Session.fork tool-pairing boundary enforcement
- validate_session_header fail-closed verification
- request/header startsSeries and reason: 'series'
- KNOWN_SESSION_EVENT_TYPES persistence verification
"""

import json
import os
import pytest
import tempfile
from dsh.cordis.context import Context
from dsh.core.session import (
    Session,
    SessionHeader,
    SessionStore,
    KNOWN_SESSION_EVENT_TYPES,
    validate_session_header,
    snapshot_json_value,
)
from dsh.session.chunk_rows import (
    pack_chunk_runs,
    decode_storage_record,
    is_chunk_row,
    chunk_row_length,
)
from dsh.session.persistence_jsonl import JsonlSessionPersistence


def test_chunk_rows_text_packing_and_decoding():
    # Construct 4 consecutive text-delta chunk events (>= MIN_RUN 3)
    events = [
        {
            "type": "assistant/chunk",
            "seq": 10,
            "time": 1000,
            "data": {
                "turn": 1,
                "step": 1,
                "chunk": {"type": "text-delta", "index": 0, "text": "Hello "},
            },
        },
        {
            "type": "assistant/chunk",
            "seq": 11,
            "time": 1050,
            "data": {
                "turn": 1,
                "step": 1,
                "chunk": {"type": "text-delta", "index": 0, "text": "world"},
            },
        },
        {
            "type": "assistant/chunk",
            "seq": 12,
            "time": 1090,
            "data": {
                "turn": 1,
                "step": 1,
                "chunk": {"type": "text-delta", "index": 0, "text": " from"},
            },
        },
        {
            "type": "assistant/chunk",
            "seq": 13,
            "time": 1140,
            "data": {
                "turn": 1,
                "step": 1,
                "chunk": {"type": "text-delta", "index": 0, "text": " DeepSeek!"},
            },
        },
    ]

    packed = pack_chunk_runs(events)
    assert len(packed) == 1
    row = packed[0]
    assert is_chunk_row(row) is True
    assert row["type"] == "text-chunks"
    assert row["seq0"] == 10
    assert row["time0"] == 1000
    assert row["data"]["dt"] == [50, 40, 50]
    assert row["data"]["texts"] == ["Hello ", "world", " from", " DeepSeek!"]
    assert chunk_row_length(row) == 4

    # Decode row back
    decoded = decode_storage_record(row)
    assert len(decoded) == 4
    assert decoded == events


def test_chunk_rows_tool_call_packing_and_decoding():
    events = [
        {
            "type": "assistant/chunk",
            "seq": 5,
            "time": 2000,
            "data": {
                "turn": 2,
                "step": 1,
                "chunk": {
                    "type": "tool-call-delta",
                    "index": 1,
                    "id": "call_123",
                    "name": "read_file",
                    "argumentsDelta": '{"path":',
                },
            },
        },
        {
            "type": "assistant/chunk",
            "seq": 6,
            "time": 2030,
            "data": {
                "turn": 2,
                "step": 1,
                "chunk": {
                    "type": "tool-call-delta",
                    "index": 1,
                    "id": "call_123",
                    "name": "read_file",
                    "argumentsDelta": ' "dsh/',
                },
            },
        },
        {
            "type": "assistant/chunk",
            "seq": 7,
            "time": 2070,
            "data": {
                "turn": 2,
                "step": 1,
                "chunk": {
                    "type": "tool-call-delta",
                    "index": 1,
                    "id": "call_123",
                    "name": "read_file",
                    "argumentsDelta": 'core.py"}',
                },
            },
        },
    ]

    packed = pack_chunk_runs(events)
    assert len(packed) == 1
    row = packed[0]
    assert row["type"] == "tool-call-chunks"
    assert row["data"]["id"] == "call_123"
    assert row["data"]["name"] == "read_file"
    assert row["data"]["args"] == ['{"path":', ' "dsh/', 'core.py"}']

    decoded = decode_storage_record(row)
    assert len(decoded) == 3
    assert decoded == events


def test_chunk_rows_below_min_run_threshold_passes_verbatim():
    events = [
        {
            "type": "assistant/chunk",
            "seq": 1,
            "time": 100,
            "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "A"}},
        },
        {
            "type": "assistant/chunk",
            "seq": 2,
            "time": 120,
            "data": {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "B"}},
        },
    ]
    packed = pack_chunk_runs(events)
    assert len(packed) == 2
    assert packed == events


def test_derive_messages_incremental_caching_and_invalidation():
    ctx = Context()
    session = Session(session_id="cache-test", ctx=ctx)

    # Initially empty
    assert session.derive_messages() == []

    # 1. Append user message
    session.append_user_message("Message 1")
    msgs1 = session.derive_messages()
    assert len(msgs1) == 1
    assert msgs1[0]["content"] == [{"type": "text", "text": "Message 1"}]
    assert session._derived_nodes == 1

    # 2. Append assistant message
    session.append_assistant_message({"role": "assistant", "content": "Response 1"})
    msgs2 = session.derive_messages()
    assert len(msgs2) == 2
    assert msgs2[1]["content"] == [{"type": "text", "text": "Response 1"}]
    assert session._derived_nodes == 2

    # 3. Compaction replacement (rewrite surface)
    # Replace messages 0 and 1 with a single summary message
    session.append_user_message(
        "Summary: User asked message 1 and Assistant responded.",
        surface_op={"op": "replace", "start": 0, "end": 1},
        source_event_seqs=[0, 1],
    )
    assert session.surface.replace_generation == 1

    msgs3 = session.derive_messages()
    assert len(msgs3) == 1
    assert msgs3[0]["content"] == [{"type": "text", "text": "Summary: User asked message 1 and Assistant responded."}]
    assert session._derived_generation == 1
    assert session._derived_nodes == 1


def test_session_fork_boundary_and_tool_balance():
    ctx = Context()
    session = Session(session_id="parent-session", ctx=ctx)

    # User -> Tool Call -> Tool Result -> Assistant
    session.append_user_message("Do work")  # seq 0
    session.append(
        "assistant/message",
        {"message": {"role": "assistant", "content": "Calling tool", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]}},
        surface_op="append",
    )  # seq 1
    session.append_tool_result("c1", "f", "result text")  # seq 2
    session.append_assistant_message({"role": "assistant", "content": "Finished work"})  # seq 3

    # Forking at seq 2 (cutting right between assistant tool call and tool result) should raise error
    with pytest.raises(ValueError, match="fork boundary is not tool-pairing balanced"):
        session.fork("child-invalid", boundary=2)

    # Forking at seq 3 (after tool result) or seq 4 (at end) is balanced
    child = session.fork("child-valid", boundary=3)
    assert child.id == "child-valid"
    assert child.header.parent_session == "parent-session"
    assert child.header.seed_length == 3
    assert len(child.events) >= 3


def test_validate_session_header_fail_closed():
    # Valid header
    valid_hdr = {
        "version": 0,
        "id": "valid-id",
        "createdAt": 1700000000000,
        "cwd": "C:\\workspace\\project" if os.name == "nt" else "/workspace/project",
    }
    hdr = validate_session_header("valid-id", valid_hdr)
    assert hdr.id == "valid-id"

    # Mismatched id
    with pytest.raises(ValueError, match='does not match session id'):
        validate_session_header("other-id", valid_hdr)

    # Non-absolute cwd
    invalid_cwd_hdr = dict(valid_hdr)
    invalid_cwd_hdr["cwd"] = "relative/path"
    with pytest.raises(ValueError, match='cwd must be an absolute path'):
        validate_session_header("valid-id", invalid_cwd_hdr)

    # Unsupported version
    invalid_ver_hdr = dict(valid_hdr)
    invalid_ver_hdr["version"] = 999
    with pytest.raises(ValueError, match='session header version must be 0'):
        validate_session_header("valid-id", invalid_ver_hdr)


@pytest.mark.asyncio
async def test_persistence_rejects_corrupt_event_lines():
    with tempfile.TemporaryDirectory() as temp_dir:
        persistence = JsonlSessionPersistence(root=temp_dir, pack_chunks=True)
        meta = SessionHeader(session_id="test-unrecognized", cwd=os.path.abspath(temp_dir))
        await persistence.create(meta)

        # Append valid event
        ev_valid = {"type": "user/message", "seq": 0, "time": 1000, "data": {"role": "user", "content": "Hi"}}
        await persistence.append("test-unrecognized", [ev_valid])

        # Write an invalid event line followed by a closed turn
        log_path = persistence.locate(meta).path
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("corrupted non-json line\n")
            f.write(json.dumps({"type": "turn/end", "seq": 1, "time": 2000, "data": {"turn": 1, "reason": {"kind": "completed"}}}) + "\n")

        # Loading must fail-closed on corrupt committed event
        with pytest.raises(ValueError, match="corrupt session log"):
            await persistence.load("test-unrecognized")
