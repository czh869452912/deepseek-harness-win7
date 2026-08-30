"""
1:1 Strict Parity Test Suite for Core Session, Agent, Agent-Loop, and deriveMessages.
Validates all interface contracts matching reference DeepSeek Harness.
"""

import asyncio
import os
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, CancelOptions, AgentRegistry, AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import (
    Session,
    SessionHeader,
    SessionStore,
    SessionPlugin,
)


@pytest.mark.asyncio
async def test_session_first_live_seq():
    """Verify first_live_seq accurately records the constructor seed boundary."""
    s1 = Session.create("session-empty")
    assert s1.first_live_seq == 0
    assert s1.firstLiveSeq == 0
    assert len(s1.events) == 0

    seed = [
        {"type": "turn/start", "seq": 0, "time": 1000, "data": {"turn": 1}},
        {"type": "user/message", "seq": 1, "time": 1001, "data": {"role": "user", "id": "m1", "content": [{"type": "text", "text": "hello"}], "source": {"kind": "user"}}, "surfaceOp": "append"},
        {"type": "assistant/message", "seq": 2, "time": 1002, "data": {"turn": 1, "step": 1, "message": {"id": "m2", "role": "assistant", "content": [{"type": "text", "text": "hi"}], "source": {"kind": "model", "provider": "deepseek", "model": "chat"}}}, "surfaceOp": "append"},
        {"type": "turn/end", "seq": 3, "time": 1003, "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]
    s2 = Session.create("session-seeded", seed=seed)
    assert s2.first_live_seq == 4
    assert s2.firstLiveSeq == 4
    # The session appends session/end-seed after seed loading
    assert len(s2.events) == 5
    assert s2.events[-1]["type"] == "session/end-seed"


@pytest.mark.asyncio
async def test_session_derive_messages_purity_and_caching():
    """Verify derive_messages returns pure surface messages without system prompt mutation."""
    session = Session.create("s-pure")
    assert session.derive_messages() == []
    assert session.deriveMessages() == []

    # 1. Append user message
    session.append("user/message", {
        "role": "user",
        "id": "u1",
        "content": [{"type": "text", "text": "user prompt"}],
        "source": {"kind": "user"},
    }, surface_op="append")

    # 2. Append empty assistant message (e.g. max tokens usage only) -> must project to None
    session.append("assistant/message", {
        "turn": 1,
        "step": 1,
        "message": {
            "role": "assistant",
            "content": [],
            "source": {"kind": "model", "provider": "p", "model": "m"},
        },
    }, surface_op="append")

    # 3. Append real assistant message
    session.append("assistant/message", {
        "turn": 1,
        "step": 2,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "assistant response"}],
            "source": {"kind": "model", "provider": "p", "model": "m"},
        },
    }, surface_op="append")

    # 4. Append tool result
    session.append("tool/result", {
        "turn": 1,
        "step": 2,
        "message": {
            "role": "user",
            "content": [{"type": "tool-result", "toolCallId": "c1", "content": [{"type": "text", "text": "ok"}]}],
            "source": {"kind": "tool", "callId": "c1"},
        },
    }, surface_op="append")

    # Pure derive_messages() has exactly 3 messages (empty assistant skipped)
    derived = session.derive_messages()
    assert len(derived) == 3
    assert derived[0]["role"] == "user"
    assert derived[1]["role"] == "assistant"
    assert derived[2]["role"] == "user"
    assert derived[2]["content"][0]["type"] == "tool-result"

    # Verify calling derive_messages does not mutate internal events
    assert all(e["type"] != "system" for e in session.events)


@pytest.mark.asyncio
async def test_session_store_flush_all_settled_and_bool_return():
    """Verify flush returns boolean and aggregates all listener errors."""
    ctx = Context()
    store = SessionStore(ctx=ctx)
    session = store.create("flush-session")

    # No listeners -> returns False
    res_empty = await store.flush(session)
    assert res_empty is False
    assert await session.flush() is False

    called = []

    async def l1(s):
        await asyncio.sleep(0.01)
        called.append("l1")

    def l2(s):
        called.append("l2")

    ctx.on("session/flush", l1)
    ctx.on("session/flush", l2)

    # Listeners registered -> returns True
    res = await store.flush(session)
    assert res is True
    assert "l1" in called and "l2" in called
    assert await session.flush() is True

    # When a listener fails, other listeners still complete and error is raised
    error_called = []

    def failing_l(s):
        error_called.append("fail")
        raise RuntimeError("disk full")

    def succeeding_l(s):
        error_called.append("succ")

    ctx2 = Context()
    store2 = SessionStore(ctx=ctx2)
    s_err = store2.create("err-session")

    ctx2.on("session/flush", failing_l)
    ctx2.on("session/flush", succeeding_l)

    with pytest.raises(RuntimeError, match="disk full"):
        await store2.flush(s_err)

    assert "fail" in error_called
    assert "succ" in error_called


@pytest.mark.asyncio
async def test_session_store_prepare_persistence():
    """Verify SessionStore.prepare with seed_source='persistence'."""
    ctx = Context()
    store = SessionStore(ctx=ctx)
    seed = [
        {"type": "turn/start", "seq": 0, "time": 100, "data": {"turn": 1}},
    ]
    meta = {
        "id": "p-session",
        "version": 0,
        "createdAt": 100,
        "cwd": "C:\\test_dir" if os.name == "nt" else "/test_dir",
    }

    prep = store.prepare(
        session_id="p-session",
        seed=seed,
        meta=meta,
        seed_source="persistence",
    )
    assert prep.session.id == "p-session"
    # Interrupted turn closer was appended by from_restore
    assert len(prep.session.events) >= 2
    assert any(e["type"] == "turn/end" for e in prep.session.events)


@pytest.mark.asyncio
async def test_agent_options_and_properties():
    """Verify AgentOptions camelCase properties and serialization."""
    opt = AgentOptions(
        provider="deepseek",
        model="deepseek-chat",
        reasoning_effort="high",
        max_tokens=8192,
    )
    assert opt.provider == "deepseek"
    assert opt.model == "deepseek-chat"
    assert opt.reasoning_effort == "high"
    assert opt.reasoningEffort == "high"
    assert opt.max_tokens == 8192
    assert opt.maxTokens == 8192

    d = opt.to_dict()
    assert d == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "reasoningEffort": "high",
        "maxTokens": 8192,
    }


@pytest.mark.asyncio
async def test_agent_cancel_keep_inbox_and_discard():
    """Verify Agent cancellation with keep_inbox=True and False."""
    session = Session.create("cancel-test")
    agent = Agent(session=session)

    agent.followup("prompt 1")
    agent.steer("guidance 1")
    assert agent.inbox.has_pending is True

    # 1. Cancel with keep_inbox = True
    agent.cancel(cause={"kind": "user"}, options=CancelOptions(keep_inbox=True))
    assert agent.is_cancelled() is True
    assert agent.isCancelled() is True
    assert agent.inbox.has_pending is True
    cause = agent.take_cancel_cause()
    assert cause == {"kind": "user"}

    # 2. Cancel with keep_inbox = False -> inbox cleared
    agent.cancel(cause={"kind": "parent"}, options=CancelOptions(keep_inbox=False))
    assert agent.inbox.has_pending is False
    assert agent.is_cancelled() is True


@pytest.mark.asyncio
async def test_agent_run_maintenance_and_when_idle():
    """Verify run_maintenance lifecycle and when_idle synchronization."""
    session = Session.create("maint-test")
    agent = Agent(session=session)

    assert agent.status == "idle"

    executed = []

    async def maint_task(abort_sig):
        assert agent.status == "idle"
        executed.append("ran")
        await asyncio.sleep(0.01)
        return 42

    res = await agent.run_maintenance(maint_task)
    assert res == 42
    assert executed == ["ran"]
    assert agent.status == "idle"

    # when_idle returns immediately on idle empty agent
    await agent.when_idle()
    await agent.whenIdle()
