"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent and @deepseek-ai/dsh-agent-loop
Covers:
- Inbox (replay, replace by id, splice normalization, duplicate id rejection, clear with canceled outcome)
- AgentRegistry (registration, lookup, session identity validation, ownership tracking, listener rollback)
- Agent & AgentLoop (cancel semantics, F2 leak guard, driver lifecycle, when_idle synchronization)
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentRegistry, AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.inbox import Inbox
from dsh.core.session import Session, SessionStore


# ============================================================================
# 1. Inbox 1:1 parity (from agent/tests/agent.spec.ts Inbox suite)
# ============================================================================

def test_inbox_rejects_invalid_durable_splice_during_reconstruction():
    session = Session(session_id="invalid-inbox-replay")
    session.append("agent/inbox/spliced", {
        "target": "next-turn",
        "start": 1,
        "inserted": [],
    })

    with pytest.raises(ValueError, match="invalid persisted inbox splice at session seq 0"):
        Inbox(session=session)


def test_inbox_replaces_pending_message_by_identity():
    session = Session(session_id="replace-inbox")
    inbox = Inbox(session=session)

    original = {"role": "user", "id": "msg-orig", "content": "original"}
    next_step = {"role": "user", "id": "msg-step", "content": "step"}
    replacement = {"role": "user", "id": "msg-repl", "content": "replacement"}
    edited_step = {"role": "user", "id": "msg-step", "content": "edited step"}

    inbox.append("next-turn", original)
    inbox.append("next-step", next_step)

    assert inbox.replace("msg-missing", replacement) is False
    assert inbox.replace("msg-orig", replacement) is True
    assert inbox.replace("msg-step", edited_step) is True

    assert inbox.next_turn == [replacement]
    assert inbox.next_step == [edited_step]

    # Replacing with an already pending id throws
    with pytest.raises(ValueError, match='message "msg-repl" is already pending'):
        inbox.replace("msg-step", replacement)


def test_inbox_splice_normalization_and_duplicate_rejection():
    session = Session(session_id="splice-inbox")
    inbox = Inbox(session=session)

    first = {"role": "user", "id": "m1", "content": "first"}
    second = {"role": "user", "id": "m2", "content": "second"}

    inbox.splice("next-turn", 0, 0, [first, second])
    assert inbox.next_turn == [first, second]

    removed = inbox.splice("next-turn", -1, 1, [])
    assert removed == [second]
    assert inbox.remove("m2") is False

    with pytest.raises(ValueError, match='message "m1" is already pending'):
        inbox.append("next-step", first)


def test_inbox_clears_pending_lists_as_durable_cancellations():
    session = Session(session_id="clear-inbox")
    inbox = Inbox(session=session)

    inbox.append("next-turn", {"role": "user", "content": "turn"})
    inbox.append("next-step", {"role": "user", "content": "step"})
    before_clear = len(session.events)

    inbox.clear()

    assert inbox.has_pending is False
    spliced_events = [e for e in session.events[before_clear:] if e.get("type") == "agent/inbox/spliced"]
    assert len(spliced_events) == 2
    for ev in spliced_events:
        assert ev["data"]["outcome"] == "canceled"

    # Subsequent clear on empty queues is a no-op
    inbox.clear()
    assert len(session.events) == before_clear + 2


# ============================================================================
# 2. AgentRegistry 1:1 parity (from agent/tests/agent.spec.ts Registry suite)
# ============================================================================

def test_agent_registry_registration_and_lifecycle_events():
    ctx = Context()
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)

    lifecycle = []
    ctx.on("agent/created", lambda payload: lifecycle.append(f"created:{payload['agent'].id}"))
    ctx.on("agent/disposed", lambda payload: lifecycle.append(f"disposed:{payload['agent'].id}"))

    session = Session(session_id="a1", ctx=ctx)
    agent = Agent(session=session, ctx=ctx)

    dispose = registry.register(agent)
    assert registry.get("a1") == agent
    assert registry.list() == [agent]
    assert registry.roots() == [agent]

    with pytest.raises(ValueError, match="already registered"):
        registry.register(agent)

    dispose()
    assert registry.get("a1") is None
    assert lifecycle == ["created:a1", "disposed:a1"]


def test_agent_registry_rejects_mismatched_session_id():
    ctx = Context()
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)

    session = Session(session_id="session-id", ctx=ctx)
    agent = Agent(session=session, ctx=ctx)
    agent.id = "agent-id"  # artificially mismatch

    with pytest.raises(ValueError, match='agent id "agent-id" does not match session id "session-id"'):
        registry.enter(agent, owner=None)
    assert registry.list() == []


def test_agent_registry_tracks_ownership_hierarchy():
    ctx = Context()
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)

    s_root = Session(session_id="root", ctx=ctx)
    s_child = Session(session_id="child", ctx=ctx)
    root = Agent(session=s_root, ctx=ctx)
    child = Agent(session=s_child, ctx=ctx)

    detach_root = registry.enter(root, owner=None)
    registry.announce(root)
    detach_child = registry.enter(child, owner=root)
    registry.announce(child)

    assert registry.list() == [root, child]
    assert registry.roots() == [root]
    assert registry.is_owned_by("child", root) is True
    assert registry.is_owned_by("root", root) is False
    assert registry.is_owned_by("missing", root) is False

    detach_child()
    assert registry.is_owned_by("child", root) is False
    detach_root()


def test_agent_registry_rolls_back_on_listener_error():
    ctx = Context()
    registry = AgentRegistry(ctx)
    ctx.set_service("agents", registry)

    lifecycle = []
    ctx.on("agent/created", lambda payload: lifecycle.append(f"created:{payload['agent'].id}"))

    def veto(payload):
        raise ValueError("creation veto")

    ctx.on("agent/created", veto)
    ctx.on("agent/disposed", lambda payload: lifecycle.append(f"disposed:{payload['agent'].id}"))

    session = Session(session_id="vetoed", ctx=ctx)
    agent = Agent(session=session, ctx=ctx)

    with pytest.raises(ValueError, match="creation veto"):
        registry.register(agent)

    assert registry.get("vetoed") is None
    assert lifecycle == ["created:vetoed", "disposed:vetoed"]


# ============================================================================
# 3. Agent.cancel F2 leak guard & loop execution
# ============================================================================

@pytest.mark.asyncio
async def test_agent_cancel_idle_f2_leak_guard():
    ctx = Context()
    session = Session(session_id="f2-guard", ctx=ctx)
    agent = Agent(session=session, ctx=ctx)

    # Cancel on idle agent with empty inbox must be a no-op
    agent.cancel(cause={"kind": "user"})
    assert agent.is_cancelled() is False
    assert agent.take_cancel_cause() is None


@pytest.mark.asyncio
async def test_agent_loop_driver_turn_execution():
    ctx = Context()
    store = SessionStore(ctx)
    ctx.set_service("sessions", store)
    loop_svc = AgentLoopService(ctx)
    ctx.set_service("agent_loop", loop_svc)

    class MockLlm:
        provider = "mock"
        model = "mock-model"

        async def stream(self, messages, tools=None):
            yield {"type": "text-delta", "index": 0, "text": "Hello, world!"}

    ctx.set_service("llm", MockLlm())

    handle = await loop_svc.create_agent("loop-agent-1")
    agent = handle.agent

    agent.send("Run turn 1")
    await agent.when_idle()

    # Verify session log recorded turn/start, user/message, assistant/message, turn/end
    event_types = [e["type"] for e in agent.session.events]
    assert "turn/start" in event_types
    assert "user/message" in event_types
    assert "assistant/message" in event_types
    assert "turn/end" in event_types

    await handle.dispose()
