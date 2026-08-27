"""
Manual compaction command plugin (`@deepseek-ai/dsh-command-compact`).
Registers `/compact` command to force immediate conversation summarization.
"""

from typing import Any, List, Optional
from dsh.cordis.plugin import Plugin


class CommandCompactPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-command-compact`: Registers `/compact` slash command.
    """

    id = "command-compact"
    name = "@deepseek-ai/dsh-command-compact"
    inject = ["commands"]

    def apply(self, ctx: Any) -> None:
        cmd_svc = ctx.get("commands")
        if not cmd_svc or not hasattr(cmd_svc, "register"):
            return

        async def exec_compact(session: Any, args: List[str]) -> str:
            compaction_svc = ctx.get("compaction")
            if not compaction_svc:
                return "Error: Compaction service is not mounted."

            agents_svc = ctx.get("agents")
            target_agent = None
            if agents_svc and hasattr(agents_svc, "current_initiator"):
                target_agent = agents_svc.current_initiator()

            if not target_agent and hasattr(session, "agent"):
                target_agent = session.agent

            if not target_agent:
                # Mock or fallback agent with session
                class _AgentWrapper:
                    def __init__(self, s):
                        self.session = s
                        self.id = getattr(s, "id", "agent-main")
                target_agent = _AgentWrapper(session)

            try:
                result = await compaction_svc.compact_now(target_agent)
                if result:
                    return f"Compaction completed. Shadowed {len(result.get('shadowedSeqs', []))} events."
                return "Compaction completed: context already compact."
            except Exception as e:
                return f"Compaction failed: {e}"

        cmd_svc.register(
            name="compact",
            description="Force manual compaction/summarization of the current conversation history.",
            handler=exec_compact,
        )
