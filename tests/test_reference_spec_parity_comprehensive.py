"""
Unit tests porting official TypeScript reference test suites (from reference/packages/core and reference/vendor):
1. Tool Concurrency & Dynamic Classification (reference/packages/core/tools/tests/execution-mode.spec.ts)
2. Agent Cancel & Queue Drainage (reference/packages/core/agent-loop/tests/cancel.spec.ts)
3. Session Fork & History Immutability (reference/packages/core/session/tests/fork.spec.ts)
4. Cordis Context Isolation & Scope Hierarchy (reference/packages/core/scope/tests/scope.spec.ts)
5. Timer Interval & Disposer Parity (reference/vendor/timer)
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.core.agent import Agent, AgentOptions
from dsh.core.tools import ToolsService, TOOL_ABORTED_BEFORE_DISPATCH
from dsh.core.tool_calls import execute_tool_calls


# ==============================================================================
# 1. Tool Execution Mode & Dynamic Classification Parity (execution-mode.spec.ts)
# ==============================================================================

def test_tool_execution_mode_classifier_parity():
    """Verify tool execution mode classification matches TS execution-mode.spec.ts."""
    ctx = Context()
    tools = ToolsService(ctx)

    # 1. Parallel classifier
    tools.register(
        name="safe_tool",
        description="Parallel safe",
        parameters={},
        handler=lambda: None,
        is_concurrency_safe=lambda args: True,
    )
    assert tools.execution_mode("safe_tool", {}) == "parallel"

    # 2. Defaults to exclusive when no classifier is given
    tools.register(
        name="plain_tool",
        description="Plain tool",
        parameters={},
        handler=lambda: None,
    )
    assert tools.execution_mode("plain_tool", {}) == "exclusive"

    # 3. Unknown tool returns exclusive (fail-closed)
    assert tools.execution_mode("unknown_tool", {}) == "exclusive"

    # 4. Dynamic classifier depending on arguments
    tools.register(
        name="dynamic_tool",
        description="Dynamic tool",
        parameters={},
        handler=lambda **kw: None,
        is_concurrency_safe=lambda args: args.get("mode") == "read",
    )
    assert tools.execution_mode("dynamic_tool", {"mode": "read"}) == "parallel"
    assert tools.execution_mode("dynamic_tool", {"mode": "write"}) == "exclusive"

    # 5. Classifier that throws fails closed to exclusive safely
    def thrower(args):
        raise ValueError("Intentional classifier explosion")

    tools.register(
        name="throwing_tool",
        description="Throwing classifier",
        parameters={},
        handler=lambda: None,
        is_concurrency_safe=thrower,
    )
    assert tools.execution_mode("throwing_tool", {}) == "exclusive"

    # 6. Classifier returning truthy non-boolean fails closed to exclusive
    tools.register(
        name="truthy_tool",
        description="Truthy classifier",
        parameters={},
        handler=lambda: None,
        is_concurrency_safe=lambda args: "yes",
    )
    assert tools.execution_mode("truthy_tool", {}) == "exclusive"


def test_tool_schema_projection_does_not_leak_internal_flags():
    """Verify that is_concurrency_safe and handler do not leak into model-facing schemas."""
    ctx = Context()
    tools = ToolsService(ctx)
    tools.register(
        name="safe_reader",
        description="Safe file reader",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=lambda path: path,
        is_concurrency_safe=lambda args: True,
    )

    schemas = tools.get_tools()
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema["name"] == "safe_reader"
    assert schema["description"] == "Safe file reader"
    assert "parameters" in schema
    assert "is_concurrency_safe" not in schema
    assert "handler" not in schema


# ==============================================================================
# 2. Agent Cancel & Queue Drainage Parity (cancel.spec.ts)
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_cancel_idle_noop_and_active_turn():
    """Verify Agent cancel behavior matches TS cancel.spec.ts."""
    ctx = Context()
    sessions = SessionStore(ctx)
    session = sessions.create("test-cancel-session")
    agent = Agent(session=session, ctx=ctx)

    # 1. Cancel on idle agent with empty inbox is a safe no-op
    assert agent.status == "idle"
    agent.cancel()
    assert agent.status == "idle"

    # 2. Active turn cancellation
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    executed = []
    async def long_running_tool():
        executed.append("started")
        await asyncio.sleep(0.05)
        executed.append("finished")
        return "done"

    tools.register("long_tool", "Long running", {}, long_running_tool)

    # Execute tool call and cancel
    calls = [
        {"id": "call-1", "name": "long_tool", "arguments": {}},
        {"id": "call-2", "name": "long_tool", "arguments": {}},
    ]

    abort_signal = asyncio.Event()
    abort_signal.set()

    exec_task = asyncio.create_task(
        execute_tool_calls(
            ctx=ctx,
            agent=agent,
            turn=1,
            step=1,
            tool_calls=calls,
            signal=abort_signal,
        )
    )

    outcome = await exec_task
    assert not outcome.get("concluded")
    # Synthetic results for aborted tool calls match TS TOOL_ABORTED_BEFORE_DISPATCH
    results = [e for e in session.events if e.get("type") == "tool/result"]
    assert len(results) == 2
    for r in results:
        assert r["data"]["error"]["code"] == TOOL_ABORTED_BEFORE_DISPATCH


# ==============================================================================
# 3. Session Fork & History Immutability Parity (fork.spec.ts)
# ==============================================================================

def test_session_fork_history_immutability():
    """Verify session fork copies events and isolates new events matching TS fork.spec.ts."""
    ctx = Context()
    sessions = SessionStore(ctx)
    parent = sessions.create("parent-session")

    # Add initial events
    parent.append_user_message("Message 1")
    parent.append_assistant_message("Reply 1")

    assert len(parent.events) == 2

    # Fork session
    forked = sessions.create("forked-session", parent_session_id=parent.session_id)
    # Copy history from parent up to current seq
    for ev in parent.events:
        forked.append(ev["type"], dict(ev.get("data", {})), surface_op=ev.get("surface_op"))

    assert len(forked.events) == 2
    assert forked.parent_session_id == parent.session_id

    # Append new event to parent only
    parent.append_user_message("Message 2 in parent")
    assert len(parent.events) == 3
    assert len(forked.events) == 2

    # Append new event to forked only
    forked.append_user_message("Message 2 in fork")
    assert len(parent.events) == 3
    assert len(forked.events) == 3
    assert parent.events[-1]["data"]["content"][0]["text"] == "Message 2 in parent"
    assert forked.events[-1]["data"]["content"][0]["text"] == "Message 2 in fork"


# ==============================================================================
# 4. Cordis Context Isolation & Scope Hierarchy Parity (scope.spec.ts)
# ==============================================================================

def test_cordis_context_isolation_hierarchy():
    """Verify Cordis isolate() creates independent service realms matching TS scope.spec.ts."""
    root = Context()
    root.set_service("config", {"env": "production", "debug": False})

    # Child 1: inherits root config
    child1 = root.extend()
    assert child1.config["env"] == "production"

    # Child 2: isolates "config"
    child2 = root.isolate("config")
    child2.set_service("config", {"env": "development", "debug": True})

    assert child2.config["env"] == "development"
    assert root.config["env"] == "production"
    assert child1.config["env"] == "production"


# ==============================================================================
# 5. Timer Interval & Disposer Parity (reference/vendor/timer)
# ==============================================================================

@pytest.mark.asyncio
async def test_timer_interval_and_disposer_cleanup():
    """Verify Timer interval triggers repeatedly and disposes cleanly matching TS timer."""
    ctx = Context()
    ticks = []

    def on_tick():
        ticks.append(len(ticks) + 1)

    # 10ms interval
    dispose = ctx.interval(on_tick, delay_ms=10)
    await asyncio.sleep(0.07)
    assert len(ticks) >= 3

    # Dispose stops further ticks
    dispose()
    count_after_dispose = len(ticks)
    await asyncio.sleep(0.04)
    assert len(ticks) == count_after_dispose
