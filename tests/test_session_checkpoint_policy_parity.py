import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.session.checkpoint_policy import SessionCheckpointPolicyPlugin
from dsh.session import checkpoint_policy_invariant


@pytest.mark.asyncio
async def test_llm_stream_waits_for_live_session_flush_before_downstream():
    ctx = Context()
    order = []

    class Session:
        id = "s"

    session = Session()

    class Sessions:
        def get(self, sid):
            return session if sid == "s" else None

        async def flush(self, _session):
            order.append("flush")

    ctx.set_service("sessions", Sessions())
    SessionCheckpointPolicyPlugin().apply(ctx)

    async def downstream(_options):
        order.append("construct")

        async def stream():
            order.append("iterate")
            yield {"type": "finish"}

        return stream()

    result = await ctx.waterfall(
        "llm/stream",
        {"sessionId": "s"},
        lambda options: downstream(options),
    )
    # The wrapper is intentionally lazy: checkpoint starts on first pull.
    assert order == []
    assert [item async for item in result] == [{"type": "finish"}]
    assert order == ["flush", "construct", "iterate"]


@pytest.mark.asyncio
async def test_pre_step_flushes_via_store_boundary():
    ctx = Context()
    flushed = []

    class Session:
        id = "s"

    class Sessions:
        async def flush(self, session):
            flushed.append(session.id)

    ctx.set_service("sessions", Sessions())
    SessionCheckpointPolicyPlugin().apply(ctx)
    await ctx.waterfall(
        "agent/pre-step",
        {"agent": type("Agent", (), {"session": Session()})()},
        lambda *_args: {"kind": "enter"},
    )
    assert flushed == ["s"]


def test_invariant_companion_namespace_and_pending_injection():
    assert checkpoint_policy_invariant.name == "session-checkpoint-policy-invariant"
    assert checkpoint_policy_invariant.inject == ["invariants"]

    class Invariants:
        def register(self, package, install):
            assert package == "@deepseek-ai/dsh-session-checkpoint-policy"
            assert callable(install)
            return lambda: None

    class Ctx:
        invariants = Invariants()

    disposer = checkpoint_policy_invariant.apply(Ctx())
    assert callable(disposer)
    assert checkpoint_policy_invariant.apply(type("NoInv", (), {})()) is None
