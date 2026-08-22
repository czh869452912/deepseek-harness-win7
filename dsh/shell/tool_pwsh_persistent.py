from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.shell.terminal import TerminalService

TRUNCATED_MESSAGE = (
    "\n<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with Select-String in order "
    "to find the line numbers of what you are looking for.</NOTE>"
)

DEFAULT_PWSH_DESCRIPTION = (
    "Run commands in a PowerShell shell\n"
    "* When invoking this tool, the contents of the \"command\" parameter does NOT need to be XML-escaped.\n"
    "* You don't have access to the internet via this tool.\n"
    "* State is persistent across command calls and discussions with the user.\n"
    "* Use native Windows paths (C:\\...) and $env:NAME variables; this is PowerShell, not bash.\n"
    "* Please avoid commands that may produce a very large amount of output.\n"
    "* Please run long lived commands in the background, e.g. 'Start-Job' or start a server with Start-Process."
)


def maybe_truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + TRUNCATED_MESSAGE


class ToolPwshPersistentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-pwsh-persistent`: Persistent PowerShell / Bash shell tool.
    """

    id = "persistent-pwsh"
    name = "@deepseek-ai/dsh-tool-pwsh-persistent"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.max_output_chars: int = int(self.config.get("maxOutputChars", 30000))

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[ToolPwshPersistentPlugin Warning] tools service unavailable")
            return

        if not ctx.has("terminal"):
            ctx.set_service("terminal", TerminalService())

        tool_name = self.config.get("tool_name", "pwsh")
        description = self.config.get("description", DEFAULT_PWSH_DESCRIPTION)

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command string to execute in the shell",
                },
                "description": {
                    "type": "string",
                    "description": "Clear, concise description of what this command does.",
                },
                "timeoutMs": {
                    "type": "integer",
                    "description": "Optional timeout in milliseconds (default: 300000)",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for this command.",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run in the background.",
                },
            },
            "required": ["command"],
        }

        tools_service.register(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=self.handle_pwsh,
        )

    def handle_pwsh(
        self,
        command: str,
        timeoutMs: Optional[int] = None,
        ctx: Optional[Any] = None,
    ) -> str:
        terminal_service = ctx.get("terminal") if ctx else None
        if not terminal_service:
            return "Error: Terminal service unavailable"

        timeout_sec = int((timeoutMs or 300000) / 1000)
        res = terminal_service.run_command(command, timeout_seconds=timeout_sec)
        output = res.get("output", "")
        exit_code = res.get("exit_code", 0)

        output_clipped = maybe_truncate(output, self.max_output_chars)

        if exit_code != 0:
            return f"[Exit Code: {exit_code}]\n{output_clipped}"
        return output_clipped if output_clipped else "(Command executed with no output)"

