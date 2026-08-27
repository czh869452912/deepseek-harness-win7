from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.shell.terminal import TerminalService

# TS tool-pwsh-persistent & tool-bash-persistent constants.
TRUNCATED_MESSAGE = (
    "<response clipped><NOTE>To save on context only part of this file has been shown to you. "
    "You should retry this tool after you have searched inside the file with Select-String in order "
    "to find the line numbers of what you are looking for.</NOTE>"
)
LOST_PREFIX_MESSAGE = (
    "<response clipped><NOTE>The beginning of this command output was dropped by the terminal scrollback limit. "
    "The following text is the earliest retained output.</NOTE>\n"
)

DEFAULT_PWSH_DESCRIPTION = (
    "Run commands in a persistent PowerShell shell. State, including the current directory "
    "and exported environment variables, persists across calls for this agent."
)

DEFAULT_BASH_DESCRIPTION = (
    "Run commands in a persistent bash shell. State, including the current directory "
    "and exported environment variables, persists across calls for this agent."
)


def maybe_truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + TRUNCATED_MESSAGE


def append_status_marker(content: str, marker: Optional[str]) -> str:
    if marker is None:
        return content
    return marker if len(content) == 0 else f"{content}\n{marker}"


class ToolPwshPersistentPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-pwsh-persistent` / `@deepseek-ai/dsh-tool-bash-persistent`:
    Persistent PowerShell / Bash shell tool over owner-isolated persistent terminal service.
    """

    id = "persistent-pwsh"
    name = "@deepseek-ai/dsh-tool-pwsh-persistent"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.backend_type: str = str(self.config.get("backendType", "shell"))
        self.timeout_ms: int = int(self.config.get("timeoutMs", 300000))
        self.max_output_chars: int = int(self.config.get("maxOutputChars", 16000))
        tool_name = str(self.config.get("tool_name", "pwsh"))
        default_description = DEFAULT_BASH_DESCRIPTION if tool_name == "bash" else DEFAULT_PWSH_DESCRIPTION
        self.description: str = str(self.config.get("description", default_description))

        if len(self.backend_type.strip()) == 0:
            raise ValueError("tool-pwsh-persistent: backendType must be non-empty")
        if self.timeout_ms <= 0:
            raise ValueError("tool-pwsh-persistent: timeoutMs must be a positive safe integer")
        if self.max_output_chars <= 0:
            raise ValueError("tool-pwsh-persistent: maxOutputChars must be a positive safe integer")
        if len(self.description.strip()) == 0:
            raise ValueError("tool-pwsh-persistent: description must be non-empty")

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[ToolPwshPersistentPlugin Warning] tools service unavailable")
            return

        tool_name = self.config.get("tool_name", "pwsh")
        shell_type = "bash" if tool_name == "bash" else "pwsh"

        if not ctx.has("terminals"):
            ctx.set_service("terminals", TerminalService(shell_type=shell_type))
        if not ctx.has("terminal"):
            ctx.set_service("terminal", ctx.get("terminals"))

        parameters = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The PowerShell command to run. Relative path is preferred in the command."
                    if tool_name != "bash"
                    else "The bash command to run. Relative path is preferred in the command.",
                },
            },
            "required": ["command"],
        }

        disposer = tools_service.register_canonical({
            "name": tool_name,
            "description": self.description,
            "parameters": parameters,
            "execute": lambda args, _exec: self.handle_pwsh(**args),
            "output": {
                "schema": {"type": "string"},
                "render": lambda _args, value: [{"type": "text", "text": str(value)}],
            },
        })
        ctx.effect(lambda: disposer)

    def handle_pwsh(
        self,
        command: str,
        ctx: Optional[Any] = None,
    ) -> str:
        if not command or not command.strip():
            return "Error: command must be a non-empty string"

        terminal_service = (ctx.get("terminals") or ctx.get("terminal")) if ctx else None
        if not terminal_service:
            return "Error: Terminal service unavailable"

        timeout_sec = max(1, int(self.timeout_ms / 1000))
        res = terminal_service.run_command(command, timeout_seconds=timeout_sec)
        output = res.get("output", "")
        exit_code = res.get("exit_code", 0)
        completed = res.get("completed", not res.get("was_reset", False))

        if not completed:
            # Timeout / shell-exit paths already render their own markers and reset notice.
            return maybe_truncate(output, self.max_output_chars)

        rendered = maybe_truncate(output, self.max_output_chars)
        marker = f"[exit code: {exit_code}]" if exit_code != 0 else None
        return append_status_marker(rendered, marker)
