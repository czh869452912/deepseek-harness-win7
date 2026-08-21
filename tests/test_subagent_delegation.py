import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.subagent.subagent_service import SubagentRegistry
from dsh.subagent.tool_subagent import ToolSubagentPlugin


@pytest.mark.asyncio
async def test_subagent_tools():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.plugin(ToolSubagentPlugin)

    tools = ctx.get("tools")
    subagents_svc: SubagentRegistry = ctx.get("subagents")

    # Spawn subagent
    spawn_res = await tools.execute_tool("subagent", {"task": "Analyze security logs"})
    assert "completed subtask" in spawn_res

    # Fork subagent
    fork_res = await tools.execute_tool("subagent_fork", {"task": "Explore alternate refactoring"})
    assert "completed task with inherited context" in fork_res

    # List agents
    list_res = await tools.execute_tool("list_agents", {})
    assert "Subagents:" in list_res
    assert "Analyze security logs" in list_res
    assert "Explore alternate refactoring" in list_res
