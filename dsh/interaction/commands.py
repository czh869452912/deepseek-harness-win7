"""
Slash command registry service (`ctx.commands`): extensible model and UI command dispatcher.
Aligned 1:1 with official `@deepseek-ai/dsh-commands`.
"""

from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class Command:
    def __init__(self, name: str, description: str, handler: Callable[..., Any], canonical: bool = False):
        self.name = name.lstrip("/")
        self.description = description
        self.handler = handler
        self.canonical = canonical


class CommandRegistry:
    """Command registry service mounted at `ctx.commands`."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._commands: Dict[str, Command] = {}

    def register(self, name: Any, description: Optional[str] = None,
                 handler: Optional[Callable[..., Any]] = None, **kwargs: Any) -> Callable[[], None]:
        """Register a command.

        The upstream API accepts a definition mapping.  The positional form is
        retained for older plugins shipped by the Python port.
        """
        canonical = isinstance(name, dict)
        if canonical:
            definition = name
            cmd_name = str(definition.get("name", "")).lstrip("/")
            description = definition.get("description", "")
            handler = definition.get("handler")
        else:
            cmd_name = str(name).lstrip("/")
        if not cmd_name or not callable(handler):
            raise TypeError("invalid command definition")
        cmd = Command(cmd_name, str(description or ""), handler, canonical=canonical)
        self._commands[cmd_name] = cmd

        def disposer():
            if cmd_name in self._commands and self._commands[cmd_name] == cmd:
                del self._commands[cmd_name]

        if hasattr(self.ctx, "effect"):
            # `effect` receives setup and expects that setup to return its
            # disposer. Passing the disposer itself unregisters immediately.
            self.ctx.effect(lambda: disposer)
        return disposer

    def has(self, name: str) -> bool:
        return name.lstrip("/") in self._commands

    def get(self, name: str) -> Optional[Command]:
        return self._commands.get(name.lstrip("/"))

    def list_commands(self) -> List[Command]:
        return list(self._commands.values())

    async def execute(self, text_or_name: str, *extra_args: Any, **kwargs: Any) -> Optional[Any]:
        if text_or_name.startswith("/"):
            parts = text_or_name.lstrip("/").split(maxsplit=1)
            name = parts[0].strip()
            args = parts[1].strip() if len(parts) > 1 else ""
            call_args = [args] if not extra_args else list(extra_args)
        else:
            name = text_or_name.lstrip("/")
            call_args = list(extra_args)

        cmd = self._commands.get(name)
        if not cmd:
            return None

        try:
            if cmd.canonical:
                raw_input = text_or_name.lstrip("/")
                if text_or_name.startswith("/"):
                    raw_input = text_or_name[len(name) + 1:]
                invocation = {
                    "commandId": "python-command",
                    "agent": kwargs.get("agent"),
                    "rawInput": raw_input,
                    "attachments": kwargs.get("attachments", ()),
                    "signal": kwargs.get("signal"),
                }
                res = cmd.handler(invocation)
            else:
                res = cmd.handler(*call_args, **kwargs)
        except TypeError:
            # Fallback for single arg handler
            res = cmd.handler(call_args[0] if call_args else "")

        if hasattr(res, "__await__"):
            res = await res
        return res



class CommandsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-commands`: Mounts `ctx.commands` service.
    """

    id = "commands"
    name = "@deepseek-ai/dsh-commands"

    def apply(self, ctx: Any) -> None:
        svc = CommandRegistry(ctx)
        ctx.set_service("commands", svc)
