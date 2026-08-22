from typing import Any, Dict, Optional


def goal_tool_execution(ctx: Any, exec_ctx: Any) -> Any:
    agent = getattr(exec_ctx, "agent", None) if exec_ctx else None
    return {"agent": agent, "exec": exec_ctx}


def require_direct_human(ctx: Any, exec_ctx: Optional[Any] = None) -> None:
    # Verify that goal creation or modification is initiated by top-level human request, not subagent
    agent = None
    if isinstance(exec_ctx, dict):
        agent = exec_ctx.get("agent")
    elif exec_ctx and hasattr(exec_ctx, "agent"):
        agent = exec_ctx.agent

    if agent and hasattr(agent, "is_subagent") and agent.is_subagent:
        raise PermissionError("Goal modification requires top-level direct human authority, subagents may not modify goals.")


def completion_authority(ctx: Any, exec_ctx: Optional[Any] = None) -> Dict[str, Any]:
    agent = None
    if isinstance(exec_ctx, dict):
        agent = exec_ctx.get("agent")
    elif exec_ctx and hasattr(exec_ctx, "agent"):
        agent = exec_ctx.agent

    if agent and hasattr(agent, "is_subagent") and agent.is_subagent:
        raise PermissionError("complete and blocked require a direct human turn or the current goal round")

    return {"kind": "direct-human"}
