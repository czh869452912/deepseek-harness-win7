from typing import Any, Dict, Optional


def require_direct_human(ctx: Any, exec_ctx: Optional[Any] = None) -> None:
    # Verify that goal creation or modification is initiated by top-level human request, not subagent
    if exec_ctx and hasattr(exec_ctx, "agent") and exec_ctx.agent:
        agent = exec_ctx.agent
        if hasattr(agent, "is_subagent") and agent.is_subagent:
            raise PermissionError("Goal modification requires top-level direct human authority, subagents may not modify goals.")
