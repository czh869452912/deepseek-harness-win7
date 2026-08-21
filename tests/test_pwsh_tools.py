import os
import sys
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.jobs.jobs_service import JobsService
from dsh.shell.tool_pwsh import ToolPwshPlugin


@pytest.mark.asyncio
async def test_tool_pwsh_one_shot_execution():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.set_service("jobs", JobsService())
    ctx.plugin(ToolPwshPlugin)

    tools: ToolsService = ctx.get("tools")
    assert tools.has("pwsh")

    # 1. Foreground command execution
    res = await tools.execute_tool("pwsh", {"command": "Write-Output 'Hello DeepSeek Win7'"})
    assert "Hello DeepSeek Win7" in res

    # 2. Background command execution
    bg_res = await tools.execute_tool("pwsh", {
        "command": "Start-Sleep -Seconds 1; Write-Output 'Done'",
        "run_in_background": True,
    })
    assert "Started background job" in bg_res
