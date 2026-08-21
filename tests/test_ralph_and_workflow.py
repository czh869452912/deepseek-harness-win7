import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.workflow.tool_ralph import ToolRalphPlugin
from dsh.workflow.tool_workflow import ToolWorkflowPlugin


@pytest.mark.asyncio
async def test_ralph_and_workflow_tools():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.plugin(ToolRalphPlugin)
    ctx.plugin(ToolWorkflowPlugin)

    tools = ctx.get("tools")

    ralph_res = await tools.execute_tool("ralph", {"objective": "Refactor auth pipeline", "max_rounds": 10})
    assert "Ralph Loop completed" in ralph_res
    assert "Refactor auth pipeline" in ralph_res

    wf_res = await tools.execute_tool("run_workflow", {"script": "steps: [build, test]"})
    assert "Workflow result:" in wf_res
    assert "Executed workflow script" in wf_res
