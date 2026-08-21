import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.core.agent import Agent, AgentOptions
from dsh.core.tools import ToolsService, TOOL_ABORTED_BEFORE_DISPATCH
from dsh.core.tool_calls import execute_tool_calls


@pytest.mark.asyncio
async def test_tool_scheduler_parallel_and_exclusive_barrier():
    ctx = Context()
    sessions = SessionStore(ctx)
    session = sessions.create("test-scheduler-session")
    agent = Agent(session=session, ctx=ctx)

    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    execution_order = []

    async def fast_read(path: str):
        await asyncio.sleep(0.01)
        execution_order.append(f"read:{path}")
        return f"read:{path}"

    async def exclusive_write(cmd: str):
        execution_order.append(f"exclusive:{cmd}")
        return f"done:{cmd}"

    tools.register("fast_read", "Read fast", {}, fast_read, execution_mode="parallel")
    tools.register("exclusive_write", "Write exclusively", {}, exclusive_write, execution_mode="exclusive")

    calls = [
        {"id": "call-1", "name": "fast_read", "arguments": {"path": "a.txt"}},
        {"id": "call-2", "name": "fast_read", "arguments": {"path": "b.txt"}},
        {"id": "call-3", "name": "exclusive_write", "arguments": {"cmd": "write_db"}},
        {"id": "call-4", "name": "fast_read", "arguments": {"path": "c.txt"}},
    ]

    outcome = await execute_tool_calls(
        ctx=ctx,
        agent=agent,
        turn=1,
        step=1,
        tool_calls=calls,
    )

    assert not outcome.get("concluded")
    # All 4 executed
    assert len(execution_order) == 4
    # Exclusive barrier must execute after call-1 and call-2, before call-4
    assert execution_order.index("exclusive:write_db") >= 2
    assert execution_order[3] == "read:c.txt"


@pytest.mark.asyncio
async def test_tool_scheduler_aborted_synthetic_result():
    ctx = Context()
    sessions = SessionStore(ctx)
    session = sessions.create("test-abort-session")
    agent = Agent(session=session, ctx=ctx)

    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    cancel_event = asyncio.Event()
    cancel_event.set()  # Already cancelled

    calls = [
        {"id": "call-1", "name": "dummy_tool", "arguments": {}},
    ]

    outcome = await execute_tool_calls(
        ctx=ctx,
        agent=agent,
        turn=1,
        step=1,
        tool_calls=calls,
        signal=cancel_event,
    )

    assert not outcome.get("concluded")
    # Check that synthetic tool result was recorded in session
    results = [e for e in session.events if e.get("type") == "tool/result"]
    assert len(results) == 1
    res_data = results[0]["data"]
    assert res_data["error"]["code"] == TOOL_ABORTED_BEFORE_DISPATCH
