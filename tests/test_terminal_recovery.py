"""Bounded process-level checks: a lock regression must fail, never hang pytest."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_terminal_restarts_after_failure(failure):
    script = '''
from dsh.shell.terminal import PersistentTerminal
import sys
terminal = PersistentTerminal()
try:
    command = "exit" if sys.argv[1] == "exit" else ("Start-Sleep -Seconds 20" if sys.platform == "win32" else "sleep 20")
    code, output, reset = terminal.execute(command, timeout_seconds=1)
    assert reset, (code, output)
    code, output, reset = terminal.execute("echo recovered", timeout_seconds=3)
    assert code == 0 and "recovered" in output and not reset, (code, output, reset)
finally:
    terminal.close()
'''
    result = subprocess.run([sys.executable, "-c", script, failure],
                            cwd=str(Path(__file__).resolve().parents[1]),
                            capture_output=True, encoding="utf-8", timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_canonical_tool_preserves_agent_state_and_isolates_siblings(tmp_path):
    from types import SimpleNamespace
    from dsh.cordis.context import Context
    from dsh.core.agent import Agent
    from dsh.core.session import Session
    from dsh.core.tools import ToolsPlugin, ToolExecutionInput
    from dsh.shell.tool_pwsh_persistent import ToolPwshPersistentPlugin
    import asyncio

    ctx = Context()
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(ToolPwshPersistentPlugin, config={"tool_name": "pwsh" if sys.platform == "win32" else "bash", "timeoutMs": 4000})
    left = Agent(Session("terminal-left"), ctx=ctx.extend())
    right = Agent(Session("terminal-right"), ctx=ctx.extend())
    tools = ctx.get("tools")
    tool_name = "pwsh" if sys.platform == "win32" else "bash"

    async def execute(agent, command):
        result = await tools.execute(ToolExecutionInput("test-call", tool_name, {"command": command},
                                     agent=agent, signal=asyncio.Event()))
        assert not result.is_error, result.error
        return "".join(b.get("text", "") for b in result.content)

    try:
        assignment = "$env:DSH_AGENT_VALUE='left-owned'" if sys.platform == "win32" else "export DSH_AGENT_VALUE=left-owned"
        read = "echo $env:DSH_AGENT_VALUE" if sys.platform == "win32" else 'echo "$DSH_AGENT_VALUE"'
        await execute(left, assignment)
        assert "left-owned" in await execute(left, read)
        assert "left-owned" not in await execute(right, read)
    finally:
        await left.ctx.fiber.dispose()
        await right.ctx.fiber.dispose()
        await ctx.fiber.dispose()
