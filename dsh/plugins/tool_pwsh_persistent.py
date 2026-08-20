from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.terminal import TerminalService


class ToolPwshPersistentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-pwsh-persistent`: Persistent PowerShell / Cmd tool for Win7.
    """

    id = "persistent-pwsh"
    name = "@deepseek-ai/dsh-tool-pwsh-persistent"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[ToolPwshPersistentPlugin Warning] tools service unavailable")
            return

        # Ensure terminal service is mounted
        if not ctx.has("terminal"):
            ctx.set_service("terminal", TerminalService())

        tool_name = self.config.get("tool_name", "pwsh")
        description = self.config.get(
            "description",
            "Run commands in a persistent PowerShell / Cmd shell on Windows 7.\n"
            "* Command state (working directory and variables) persists across calls.\n"
            "* Use native Windows paths (C:\\...) and PowerShell syntax.\n"
        )

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command string to execute in the shell"
                },
                "timeoutMs": {
                    "type": "integer",
                    "description": "Optional timeout in milliseconds"
                }
            },
            "required": ["command"]
        }

        tools_service.register(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=self.handle_pwsh
        )

    def handle_pwsh(
        self,
        command: str,
        timeoutMs: Optional[int] = None,
        ctx: Optional[Any] = None
    ) -> str:
        terminal_service = ctx.get("terminal") if ctx else None
        if not terminal_service:
            return "Error: Terminal service unavailable"

        timeout_sec = int((timeoutMs or 300000) / 1000)
        res = terminal_service.run_command(command, timeout_seconds=timeout_sec)
        output = res.get("output", "")
        if res.get("exit_code") != 0:
            return f"[Exit Code: {res['exit_code']}]\n{output}"
        return output if output else "(Command executed with no output)"
