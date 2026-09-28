import asyncio
import os
import sys
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.jobs.local import LocalJobRegistry
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.shell.shell_env import ShellEnvPlugin
from dsh.shell.tool_pwsh import ToolPwshPlugin


@pytest.mark.asyncio
async def test_tool_pwsh_one_shot_execution():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    await ctx.plugin(LocalJobRegistry)
    await ctx.plugin(LocalSubprocessRuntime)
    ctx.get("jobs").attach_controller("test")
    # The base bundle mounts shell-env before tool-pwsh; the tool consumes its
    # `ctx.shellEnv` snapshot for every execution.
    await ctx.plugin(ShellEnvPlugin)
    fiber = await ctx.plugin(ToolPwshPlugin)

    tools: ToolsService = fiber.ctx.get("tools")
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
    job_id = bg_res.split()[3]
    await ctx.get("jobs").wait(job_id, 5000)
    assert "Done" in ctx.get("jobs").read(job_id)["text"]
    await ctx.fiber.dispose()
