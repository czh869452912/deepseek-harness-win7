import asyncio
import functools
import threading
from typing import Any, Dict, Optional
from weakref import WeakKeyDictionary
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
        self._owned_terminals = WeakKeyDictionary()

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
            if hasattr(ctx, "logger"):
                ctx.logger("persistent-pwsh").warn("tools service unavailable")
            return

        cfg = self.config or {}
        tool_name = cfg.get("tool_name", "pwsh")
        shell_type = "bash" if tool_name == "bash" else "pwsh"

        if not ctx.has("terminals"):
            terminals = TerminalService(shell_type=shell_type)
            ctx.set_service("terminals", terminals)
            ctx.effect(lambda: terminals.close)
        else:
            terminals = ctx.get("terminals")
        if not ctx.has("terminal"):
            ctx.set_service("terminal", terminals)

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
            "execute": lambda args, execution: self.execute_owned(ctx, args, execution, shell_type),
            "output": {
                "schema": {"type": "string"},
                "render": lambda _args, value: [{"type": "text", "text": str(value)}],
            },
        })
        ctx.effect(lambda: disposer)

    async def execute_owned(self, ctx, args, execution, shell_type):
        agent = getattr(execution, "agent", None)
        if agent is None:
            terminal = ctx.get("terminals") or ctx.get("terminal")
        else:
            terminal = self._owned_terminals.get(agent)
            if terminal is None:
                terminal = TerminalService(cwd=agent.session.header.cwd, shell_type=shell_type)
                self._owned_terminals[agent] = terminal
                agent.ctx.effect(lambda: terminal.close)
        if terminal is None:
            raise RuntimeError("Terminal service unavailable")
        cancelled = threading.Event()
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(None, functools.partial(
            terminal.run_command, args["command"],
            timeout_seconds=max(1, self.timeout_ms // 1000), cancelled=cancelled))
        signal = getattr(execution, "signal", None)
        try:
            while not operation.done():
                is_set = getattr(signal, "is_set", None)
                if (is_set() if callable(is_set) else getattr(signal, "aborted", False)):
                    cancelled.set()
                await asyncio.wait([operation], timeout=0.05)
            result = operation.result()
        except asyncio.CancelledError:
            cancelled.set()
            await asyncio.shield(operation)
            raise
        output = maybe_truncate(result.get("output", ""), self.max_output_chars)
        status = result.get("exit_code", 0)
        return append_status_marker(output, "[exit code: {}]".format(status) if status and result.get("completed") else None)

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
