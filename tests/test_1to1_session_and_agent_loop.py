"""
Unit tests verifying 1:1 parity and bugfixes for Session & Agent Loop subsystems.
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.agent_loop import AgentLoopService, AgentLoopPlugin
from dsh.core.runtime_context import RuntimeContextProjection
from dsh.core.session import Session, SessionHeader, SessionStore, SessionPlugin
from dsh.session.checkpoint_policy import SessionCheckpointPolicyPlugin, aborted_before_dispatch_result
from dsh.session.coordinator import PersistenceCoordinator, WriteBehindQueue
from dsh.session.persistence_jsonl import JsonlSessionPersistence
from dsh.session.stats import SessionStatsPlugin
from dsh.session.title import SessionTitlePlugin, normalize_session_title


def test_runtime_context_eviction_on_replacement_surface_event():
    ctx = Context()
    SessionPlugin().apply(ctx)
    session = ctx.get("sessions").create("test-rc-eviction")

    # Append an initial owned user/message
    ev1 = session.append(
        "user/message",
        {
            "content": "Snapshot 1",
            "source": {"kind": "plugin", "plugin": "@deepseek-ai/dsh-system-prompt"},
        },
        surface_op="append",
    )

    proj = RuntimeContextProjection(ctx, session)
    assert proj.retained is not None
    assert proj.retained["text"] == "Snapshot 1"

    # Emit a replacement surface event that replaces ev1
    session.append(
        "user/message",
        {
            "content": "Snapshot 2",
            "source": {"kind": "plugin", "plugin": "@deepseek-ai/dsh-system-prompt"},
        },
        surface_op={"op": "replace", "start": 0, "end": 0},
        source_event_seqs=[ev1["seq"]],
    )

    # Because ev1 was replaced, proj.retained should be updated or cleared
    assert proj.retained is not None
    assert proj.retained["seq"] == 1


@pytest.mark.asyncio
async def test_session_checkpoint_policy_plugin():
    ctx = Context()
    SessionPlugin().apply(ctx)
    SessionCheckpointPolicyPlugin().apply(ctx)

    store: SessionStore = ctx.get("sessions")
    session = store.create("sess-chk")

    flush_called = False

    async def mock_flush(s=None):
        nonlocal flush_called
        flush_called = True

    store.flush = mock_flush

    agent = Agent(session=session, ctx=ctx)
    payload = {"agent": agent}

    # Test pre-step waterfall
    await ctx.waterfall("agent/pre-step", payload, lambda *_args: None)
    assert flush_called is True


@pytest.mark.asyncio
async def test_persistence_coordinator(tmp_path):
    backend = JsonlSessionPersistence(root=str(tmp_path))
    coord = PersistenceCoordinator(backend=backend)

    meta = SessionHeader(session_id="s1")
    await coord.create(meta)

    await coord.append("s1", [{"type": "user/message", "seq": 0, "time": 1000, "data": {"content": "Hello"}}])

    inspection = await coord.load("s1")
    assert len(inspection.events) == 1
    assert inspection.events[0]["data"]["content"] == "Hello"

    snapshots = await coord.list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0].header.id == "s1"
    assert snapshots[0].revision is not None


def test_plugin_inject_declarations():
    assert SessionCheckpointPolicyPlugin.inject == ["llm", "sessionPersistence", "sessions", "tools"]
    assert SessionStatsPlugin.inject == ["sessionProjections"]
    assert SessionTitlePlugin.inject == []


def test_session_title_normalization():
    raw = "\x1b[31mHello\x1b[0m \x07World\r\n"
    assert normalize_session_title(raw) == "Hello World"
