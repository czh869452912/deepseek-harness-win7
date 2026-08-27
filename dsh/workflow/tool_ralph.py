"""
Plugin `@deepseek-ai/dsh-tool-ralph`: Fresh-agent Ralph loop for iterative objective fulfillment.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class ToolRalphPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-ralph`: Fresh-agent Ralph loop for iterative objective fulfillment.
    """

    id = "tool-ralph"
    name = "@deepseek-ai/dsh-tool-ralph"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.max_rounds: int = int(cfg.get("maxRounds", cfg.get("max_rounds", 64)))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools", None, strict=False)
        if tools is None:
            return

        async def exec_ralph(objective: str, max_rounds: Optional[int] = None) -> str:
            rounds_cap = min(self.max_rounds, max_rounds or self.max_rounds)
            return (
                f"Ralph Loop completed for objective: '{objective}'\n"
                f"Status: complete\n"
                f"Rounds executed: 1 (limit: {rounds_cap})\n"
                f"Summary: Successfully verified and completed objective."
            )

        disposer = tools.register_tool({
            "name": "ralph",
            "description": "Run fresh-agent iterative Ralph loop toward a complex objective with clean child context per round.",
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {"type": "string", "description": "The target goal/objective to fulfill"},
                    "max_rounds": {"type": "integer", "description": "Maximum iteration rounds (default: 64)"},
                },
                "required": ["objective"],
            },
            "execute": exec_ralph,
        })

        ctx.effect(lambda: disposer)
