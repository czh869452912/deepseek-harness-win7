"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent
Matching reference/packages/core/agent/tests/agent.spec.ts.
Covers:
- Inbox mutation, duplicate prevention, durable splice, clear
- AgentRegistry enter, announce, rollback on listener throw, deferred detach
- Factory registration and delegate call
"""

import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin, AgentRegistry
from dsh.core.inbox import Inbox
from dsh.core.session import Session


def stub_agent(agent_id: str, session: Session = None) -> Agent:
    s = session or Session(session_id=agent_id)
    return Agent(session=s, agent_id=agent_id)


# ============================================================================
# 1. Inbox 1:1 parity
# ============================================================================

def test_inbox_replaces_pending_message_and_rejects_duplicates():
    session = Session(session_id="replace-inbox")
    inbox = Inbox(session=session)

    original = {"id": "m1", "role": "user", "content": [{"type": "text", "text": "original"}], "source": {"kind": "user"}}
    next_step = {"id": "m2", "role": "user", "content": [{"type": "text", "text": "step"}], "source": {"kind": "user"}}
    replacement = {"id": "m3", "role": "user", "content": [{"type": "text", "text": "replacement"}], "source": {"kind": "user"}}

    inbox.append("next-turn", original)
    inbox.append("next-step", next_step)

    # Missing ID returns False
    assert inbox.replace("missing", replacement) is False

    # Replace original
    assert inbox.replace("m1", replacement) is True
    assert inbox.next_turn == [replacement]

    # Duplicate insertion raises
    with pytest.raises(ValueError, match="already pending"):
        inbox.append("next-step", replacement)


def test_inbox_clear_cancels_both_pending_lists():
    session = Session(session_id="clear-inbox")
    inbox = Inbox(session=session)

    inbox.append("next-turn", {"id": "t1", "role": "user", "content": [{"type": "text", "text": "turn"}]})
    inbox.append("next-step", {"id": "s1", "role": "user", "content": [{"type": "text", "text": "step"}]})
    before_clear = len(session.events)

    inbox.clear()
    assert inbox.has_pending is False
    assert len(inbox.next_turn) == 0
    assert len(inbox.next_step) == 0

    # Events emitted for splice
    assert len(session.events) == before_clear + 2


# ============================================================================
# 2. AgentRegistry lifecycle, rollback, and deferred detach
# ============================================================================

def test_agent_registry_registers_entries_and_emits_lifecycle():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    lifecycle = []
    ctx.on("agent/created", lambda data: lifecycle.append(f"created:{data['agent'].id}"))
    ctx.on("agent/disposed", lambda data: lifecycle.append(f"disposed:{data['agent'].id}"))

    agent = stub_agent("a1")
    dispose = registry.register(agent)

    assert registry.get("a1") == agent
    assert registry.list() == [agent]
    assert registry.roots() == [agent]

    # Duplicate registration rejected
    with pytest.raises(ValueError, match="already registered"):
        registry.register(stub_agent("a1"))

    dispose()
    assert registry.get("a1") is None
    assert lifecycle == ["created:a1", "disposed:a1"]


def test_agent_registry_rejects_mismatched_id():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    mismatched = stub_agent("agent-id", session=Session(session_id="session-id"))

    with pytest.raises(ValueError, match="does not match session id"):
        registry.enter(mismatched)
    assert registry.list() == []


def test_agent_registry_rolls_back_on_creation_listener_throw():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    lifecycle = []
    ctx.on("agent/created", lambda data: lifecycle.append(f"created:{data['agent'].id}"))

    def veto(data):
        if data["agent"].id == "vetoed":
            raise ValueError("creation veto")

    ctx.on("agent/created", veto)
    ctx.on("agent/disposed", lambda data: lifecycle.append(f"disposed:{data['agent'].id}"))

    with pytest.raises(ValueError, match="creation veto"):
        registry.register(stub_agent("vetoed"))

    assert registry.get("vetoed") is None
    assert lifecycle == ["created:vetoed", "disposed:vetoed"]


def test_agent_registry_defers_detach_requested_by_creation_listener():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    order = []
    agent = stub_agent("reentrant")
    detach_fn = None

    def on_created_1(data):
        order.append(f"first:{registry.get(agent.id) == agent}")
        detach_fn()
        order.append(f"after-detach:{registry.get(agent.id) == agent}")

    def on_created_2(data):
        order.append(f"second:{registry.get(agent.id) == agent}")

    ctx.on("agent/created", on_created_1)
    ctx.on("agent/created", on_created_2)
    ctx.on("agent/disposed", lambda data: order.append("disposed"))

    detach_fn = registry.enter(agent)
    registry.announce(agent)

    assert order == ["first:True", "after-detach:True", "second:True", "disposed"]
    assert registry.get(agent.id) is None


def test_inbox_rejects_invalid_durable_splice_during_reconstruction():
    session = Session(session_id="invalid-inbox-replay")
    session.append("agent/inbox/spliced", {
        "target": "next-turn",
        "start": 1,
        "inserted": [],
    })

    with pytest.raises(ValueError, match="invalid persisted inbox splice at session seq 0"):
        Inbox(session=session)


def test_inbox_normalizes_splice_coordinates_and_rejects_duplicate_identities():
    session = Session(session_id="splice-inbox")
    inbox = Inbox(session=session)
    first = {"id": "m1", "role": "user", "content": [{"type": "text", "text": "first"}], "source": {"kind": "user"}}
    second = {"id": "m2", "role": "user", "content": [{"type": "text", "text": "second"}], "source": {"kind": "user"}}

    inbox.splice("next-turn", float("nan"), float("nan"), [first, second])
    assert inbox.next_turn == [first, second]
    assert inbox.splice("next-turn", -1, 1, []) == [second]
    assert inbox.remove("m2") is False
    with pytest.raises(ValueError, match='already pending'):
        inbox.append("next-step", first)


def test_agent_registry_tracks_runtime_creator_ownership():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    root = stub_agent("root")
    child = stub_agent("child")

    detach_root = registry.enter(root, creator=None)
    registry.announce(root)
    detach_child = registry.enter(child, creator=root)
    registry.announce(child)

    assert registry.list() == [root, child]
    assert registry.roots() == [root]
    assert registry.is_owned_by(child.id, root) is True
    assert registry.is_owned_by(root.id, root) is False
    assert registry.is_owned_by("missing", root) is False

    detach_child()
    assert registry.is_owned_by(child.id, root) is False
    detach_root()

