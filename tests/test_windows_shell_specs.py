import os
import sys
from dsh.shell.tool_pwsh import ToolPwshPlugin
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin


def test_windows_shell_pwsh_tool_registration():
    ctx = Context()
    ctx.plugin(ToolsPlugin)
    ctx.plugin(ToolPwshPlugin)

    tools_svc = ctx.get("tools")
    assert tools_svc.has_tool("pwsh")

    tool = tools_svc.get_tool("pwsh")
    assert tool is not None
    assert "command" in tool.parameters.get("properties", {})


def test_windows_shell_environment_encoding_sanity():
    # Verify sys.stdout/stderr encoding or reconfigure
    if hasattr(sys.stdout, "encoding") and sys.stdout.encoding:
        assert sys.stdout.encoding.lower() in ("utf-8", "cp936", "cp65001", "ansi", "utf8", "gbk")
