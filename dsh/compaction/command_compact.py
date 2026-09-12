"""
Manual compaction command plugin (`@deepseek-ai/dsh-command-compact`).
Registers the `/compact` command to force immediate conversation summarization
through the backend-independent compaction seam, matching
reference/packages/compaction/command-compact/src/index.ts.
"""

from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class CommandCompactPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-command-compact`: Registers the `/compact` command.
    """

    id = "command-compact"
    name = "@deepseek-ai/dsh-command-compact"
    inject = ["commands"]

    def apply(self, ctx: Any) -> None:
        cmd_svc = ctx.get("commands")
        if not cmd_svc or not hasattr(cmd_svc, "register"):
            return

        async def exec_compact(invocation: Any) -> Dict[str, Any]:
            compaction_svc = ctx.get("compaction")
            if not compaction_svc:
                return {"kind": "error", "text": "Error: Compaction service is not mounted."}

            agent = getattr(invocation, "agent", None)
            if agent is None:
                agents_svc = ctx.get("agents")
                if agents_svc and hasattr(agents_svc, "current_initiator"):
                    agent = agents_svc.current_initiator()
            if agent is None:
                return {"kind": "error", "text": "Error: No agent is available for compaction."}

            try:
                result = await compaction_svc.compact_now(agent)
                if result:
                    shadowed = result.get("shadowedSeqs", []) if isinstance(result, dict) else []
                    return {
                        "kind": "success",
                        "text": f"Compaction completed. Shadowed {len(shadowed)} events.",
                    }
                return {"kind": "success", "text": "Compaction completed: context already compact."}
            except Exception as e:
                return {"kind": "error", "text": f"Compaction failed: {e}"}

        cmd_svc.register({
            "name": "compact",
            "description": "Force manual compaction/summarization of the current conversation history.",
            "handler": exec_compact,
        })
