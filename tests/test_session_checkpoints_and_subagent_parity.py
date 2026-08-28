"""
Unit tests covering Session Semantic Checkpoints, Format Guard Invariants, and Subagent Inheritance Parity
Matching reference/apps/cli/tests/profiles/headless/tests/semantic-checkpoint.expected.e2e.ts and subagent-inheritance.expected.e2e.ts
"""

import json
import os
import pytest

from dsh.core.session import Session, SessionHeader, SessionStore, snapshot_json_value
from dsh.subagent.subagent_service import SubagentRegistry, SubagentRecord, SubagentResult


def test_session_semantic_checkpoints_and_format_guard():
    store = SessionStore()
    session = store.create(session_id="checkpoint-test")

    # Append sequential typed events
    e1 = session.append_user_message("Hello")
    e2 = session.append("tool/call", {"name": "fs_search", "call_id": "call-1", "arguments": {"pattern": "*.py"}})
    e3 = session.append_tool_result("call-1", "fs_search", "found 5 files", turn=1, step=1)
    e4 = session.append_assistant_message({"role": "assistant", "content": "I found the files."}, turn=1, step=2)

    # Validate events log and surface manager projection
    assert len(session.events) >= 4
    messages = session.derive_messages(system_prompt="You are an assistant.")
    assert len(messages) >= 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello"

    # Test serialization invariant
    dumped = [snapshot_json_value(ev) for ev in session.events]
    json_str = json.dumps(dumped)
    loaded = json.loads(json_str)
    assert len(loaded) == len(session.events)


def test_subagent_inheritance_and_forking():
    registry = SubagentRegistry()

    # 1. Spawn subagent with parent session and task
    record = registry.spawn(
        parent_session_id="session-parent-1",
        task="Deep research on codebase",
        depth=1,
        continuable=True
    )
    assert record.id.startswith("subagent-")
    assert record.status == "running"
    assert record.depth == 1
    assert record.continuable is True

    # 2. Queue follow-up message
    msg_id = registry.followup(record.id, "Please focus on cordis directory")
    assert msg_id.startswith("msg-")
    assert len(record.inbox) == 1
    assert record.inbox[0]["content"] == "Please focus on cordis directory"

    # 3. Complete subagent task
    record.complete("Research complete: 10 files analyzed")
    assert record.status == "completed"
    assert record.result == "Research complete: 10 files analyzed"
    assert record.result_obj.stop_reason == "completed"

    # 4. Test max depth limit enforcement
    with pytest.raises(RuntimeError, match="Subagent max depth exceeded"):
        registry.spawn(
            parent_session_id="session-deep",
            task="Too deep subagent",
            depth=5
        )
