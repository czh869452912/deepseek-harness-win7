from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.services.agent_loop import AgentLoopService
from dsh.services.session import SessionService
from dsh.services.tools import ToolsService


class AgentLoopPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-loop`: Core agent loop & session services.
    """

    id = "agent-loop"
    name = "@deepseek-ai/dsh-agent-loop"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tools"):
            ctx.set_service("tools", ToolsService(ctx))

        if not ctx.has("sessions"):
            ctx.set_service("sessions", SessionService())

        agent_loop = AgentLoopService(ctx)
        ctx.set_service("agent_loop", agent_loop)
