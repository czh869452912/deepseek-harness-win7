"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent Initiator Scoping
Matching reference/packages/core/agent/tests/agent-initiator.spec.ts.
Covers:
- require_initiator vs current_initiator
- with_initiator sync and async preservation
- overlapping initiator isolation
- nested and without_initiator boundaries
- lifecycle draining and disposal barrier
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin, AgentRegistry
from dsh.core.session import Session


def create_mock_agent(agent_id: str) -> Agent:
    session = Session(session_id=agent_id)
    return Agent(session=session)


@pytest.mark.asyncio
async def test_agent_registry_initiator_absent_and_required():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)

    assert registry.current_initiator() is None
    with pytest.raises(RuntimeError, match="no initiating agent is active"):
        registry.require_initiator()


@pytest.mark.asyncio
async def test_agent_registry_initiator_sync_and_async_preservation():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    agent = create_mock_agent("a1")
    value = {"result": True}

    def sync_op():
        assert registry.require_initiator() == agent
        return value

    assert registry.with_initiator(agent, sync_op) == value

    async def async_op():
        assert registry.require_initiator() == agent
        await asyncio.sleep(0.001)
        assert registry.require_initiator() == agent
        return value

    res = await registry.with_initiator_async(agent, async_op())
    assert res == value
    assert registry.current_initiator() is None


@pytest.mark.asyncio
async def test_agent_registry_isolates_overlapping_initiators():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    a = create_mock_agent("a")
    b = create_mock_agent("b")

    both_started = asyncio.Event()
    release = asyncio.Event()
    starts = 0

    async def run(ag: Agent):
        nonlocal starts
        assert registry.require_initiator() == ag
        starts += 1
        if starts == 2:
            both_started.set()
        await release.wait()
        assert registry.require_initiator() == ag

    task_a = asyncio.create_task(registry.with_initiator_async(a, run(a)))
    task_b = asyncio.create_task(registry.with_initiator_async(b, run(b)))

    await both_started.wait()
    assert registry.current_initiator() is None

    release.set()
    await asyncio.gather(task_a, task_b)


@pytest.mark.asyncio
async def test_agent_registry_restores_nested_and_explicitly_cleared_boundaries():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    parent = create_mock_agent("parent")
    child = create_mock_agent("child")

    def outer():
        assert registry.require_initiator() == parent

        def inner():
            assert registry.require_initiator() == child

        registry.with_initiator(child, inner)
        assert registry.require_initiator() == parent

        def cleared():
            assert registry.current_initiator() is None
            with pytest.raises(RuntimeError, match="no initiating agent is active"):
                registry.require_initiator()

        registry.without_initiator(cleared)
        assert registry.require_initiator() == parent

    registry.with_initiator(parent, outer)
    assert registry.current_initiator() is None


@pytest.mark.asyncio
async def test_agent_registry_draining_and_disposal_barrier():
    ctx = Context()
    registry = AgentRegistry(ctx=ctx)
    initiator = create_mock_agent("draining")
    release = asyncio.Event()

    async def run():
        await release.wait()
        assert registry.require_initiator() == initiator

    task = asyncio.create_task(registry.with_initiator_async(initiator, run()))
    await asyncio.sleep(0.001)

    # Start disposal in background
    dispose_task = asyncio.create_task(registry.dispose_initiators())
    await asyncio.sleep(0.001)

    assert registry.initiator_state in ("closing", "disposed")

    # New entries rejected
    with pytest.raises(RuntimeError, match="cannot enter agent initiator scope"):
        registry.with_initiator(initiator, lambda: 1)

    release.set()
    await task
    await dispose_task

    assert registry.initiator_state == "disposed"
    assert registry.current_initiator() is None
    with pytest.raises(RuntimeError, match="agent initiator scope is disposed"):
        registry.require_initiator()
