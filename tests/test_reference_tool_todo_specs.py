import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.todo.tool_todo import ToolTodoPlugin, compose_todo_description


def fake_agent(ctx, name="agent-1"):
    sess_store = ctx.get("sessions")
    session = sess_store.create(name)
    agent = Agent(agent_id=name, session=session, ctx=ctx)
    ctx.get("agents").enter(agent)
    return agent


@pytest.fixture
def setup_todo_ctx():
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    sess_plugin = SessionPlugin()
    sess_plugin.apply(ctx)
    agent_plugin = AgentPlugin()
    agent_plugin.apply(ctx)
    return ctx


def test_requires_allow_parallel_in_progress_config():
    with pytest.raises(ValueError, match="allowParallelInProgress is required"):
        ToolTodoPlugin({})


@pytest.mark.asyncio
async def test_rejects_non_agent_caller(setup_todo_ctx):
    ctx = setup_todo_ctx
    todo_plugin = ToolTodoPlugin({"allowParallelInProgress": True})
    todo_plugin.apply(ctx)

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": "todo_write",
        "arguments": {"todos": [{"content": "task 1", "status": "pending"}]},
    })
    assert res.is_error is True
    assert "requires an owning agent session" in res.content[0]["text"]


@pytest.mark.asyncio
async def test_rejects_empty_or_duplicate_content(setup_todo_ctx):
    ctx = setup_todo_ctx
    todo_plugin = ToolTodoPlugin({"allowParallelInProgress": True})
    todo_plugin.apply(ctx)
    agent = fake_agent(ctx, "agent-dup")

    tools_svc = ctx.get("tools")
    res1 = await tools_svc.execute({
        "name": "todo_write",
        "arguments": {"todos": [{"content": "   ", "status": "pending"}]},
        "agent": agent,
    })
    assert res1.is_error is True
    assert "must be a non-empty string" in res1.content[0]["text"]

    res2 = await tools_svc.execute({
        "name": "todo_write",
        "arguments": {"todos": [
            {"content": "task A", "status": "pending"},
            {"content": "task A", "status": "in_progress"},
        ]},
        "agent": agent,
    })
    assert res2.is_error is True
    assert "duplicate content" in res2.content[0]["text"]


@pytest.mark.asyncio
async def test_rejects_multiple_in_progress_when_parallel_disabled(setup_todo_ctx):
    ctx = setup_todo_ctx
    todo_plugin = ToolTodoPlugin({"allowParallelInProgress": False})
    todo_plugin.apply(ctx)
    agent = fake_agent(ctx, "agent-single")

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": "todo_write",
        "arguments": {"todos": [
            {"content": "task 1", "status": "in_progress"},
            {"content": "task 2", "status": "in_progress"},
        ]},
        "agent": agent,
    })
    assert res.is_error is True
    assert "at most one task may be in_progress" in res.content[0]["text"]


@pytest.mark.asyncio
async def test_appends_todo_write_event_to_agent_session(setup_todo_ctx):
    ctx = setup_todo_ctx
    todo_plugin = ToolTodoPlugin({"allowParallelInProgress": True})
    todo_plugin.apply(ctx)
    agent = fake_agent(ctx, "agent-ok")

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute({
        "name": "todo_write",
        "arguments": {"todos": [
            {"content": "step 1", "status": "completed"},
            {"content": "step 2", "status": "in_progress"},
            {"content": "step 3", "status": "pending"},
        ]},
        "agent": agent,
    })
    assert res.is_error is False
    assert "1 pending, 1 in progress, 1 completed" in res.content[0]["text"]

    writes = [ev for ev in agent.session.events if ev.get("type") == "todo/write"]
    assert len(writes) == 1
    assert len(writes[0]["data"]["todos"]) == 3