"""
Semantic durability checkpoints for model requests, top-level tool dispatch, and completed agent steps.
Aligned 1:1 with official `@deepseek-ai/dsh-session-checkpoint-policy`.
"""

import asyncio
from typing import Any, Callable, Dict, Optional
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.tools import TOOL_ABORTED_BEFORE_DISPATCH, ToolExecutionResult


def aborted_before_dispatch_result() -> ToolExecutionResult:
    return ToolExecutionResult(
        content=[{"type": "text", "text": "Error: tool call aborted before dispatch"}],
        is_error=True,
        error={
            "message": "tool call aborted before dispatch",
            "info": {"name": "AbortError", "code": TOOL_ABORTED_BEFORE_DISPATCH},
        },
    )


class SessionCheckpointPolicyPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-checkpoint-policy`:
    Install semantic checkpoint listeners on llm/stream, tools/execute, and agent/pre-step.
    """

    id = "session-checkpoint-policy"
    name = "@deepseek-ai/dsh-session-checkpoint-policy"
    inject = ["sessions"]

    def apply(self, ctx: Context) -> None:
        async def on_pre_step(payload: Dict[str, Any], next_fn: Callable[..., Any]) -> Any:
            agent = payload.get("agent")
            if agent and hasattr(agent, "session"):
                sessions = ctx.get("sessions")
                if sessions and hasattr(sessions, "flush"):
                    await sessions.flush(agent.session)
            return await next_fn(payload) if callable(next_fn) else None

        async def on_tools_execute(exec_input: Any, next_fn: Callable[..., Any]) -> Any:
            agent = getattr(exec_input, "agent", None)
            parent = getattr(exec_input, "parent", None)
            if agent is not None and parent is None:
                sessions = ctx.get("sessions")
                if sessions and hasattr(sessions, "flush"):
                    await sessions.flush(agent.session)
                signal = getattr(exec_input, "signal", None)
                if signal and (
                    (isinstance(signal, asyncio.Event) and signal.is_set())
                    or getattr(signal, "aborted", False)
                ):
                    return aborted_before_dispatch_result()
            return await next_fn(exec_input) if callable(next_fn) else None

        ctx.on("agent/pre-step", on_pre_step)
        ctx.on("tools/execute", on_tools_execute)
