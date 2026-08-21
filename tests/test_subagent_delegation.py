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

    # 1. Spawn foreground subagent (with description + prompt)
    spawn_res = await tools.execute_tool("subagent", {
        "description": "Analyze security logs",
        "prompt": "Inspect /var/log/auth.log for brute-force attacks"
    })
    assert "completed subtask" in spawn_res

    # 2. Fork subagent
    fork_res = await tools.execute_tool("subagent_fork", {
        "description": "Explore alternate refactoring",
        "prompt": "Evaluate migrating to async queue"
    })
    assert "completed task with inherited context" in fork_res

    # 3. Spawn background subagent
    bg_res = await tools.execute_tool("subagent", {
        "description": "Background task",
        "prompt": "Compile assets",
        "run_in_background": True
    })
    assert "started background subagent job" in bg_res
    bg_id = bg_res.split()[-1]

    # 4. Send message to background subagent
    msg_res = await tools.execute_tool("send_message", {
        "subagent_id": bg_id,
        "message": "Also clean cache after compile"
    })
    assert f"message queued as the next turn for subagent {bg_id}" in msg_res

    # 5. Interrupt agent
    interrupt_res = await tools.execute_tool("interrupt_agent", {
        "agent_id": bg_id
    })
    assert f"interrupt requested for agent {bg_id}" in interrupt_res

    # 6. List agents
    list_res = await tools.execute_tool("list_agents", {})
    assert "Subagents:" in list_res
    assert bg_id in list_res

