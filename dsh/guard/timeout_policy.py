"""
Cooperative tool-call timeout enforcer (`@deepseek-ai/dsh-tool-call-timeout-policy`).
"""

import asyncio
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin

TOOL_TIMEOUT = "TOOL_TIMEOUT"


def tool_timeout_result(timeout_ms: int) -> Dict[str, Any]:
    message = f"tool call timed out after {timeout_ms}ms"
    return {
        "content": [{"type": "text", "text": f"Error: {message}"}],
        "isError": True,
        "error": {
            "message": message,
            "info": {"name": "ToolTimeoutError", "code": TOOL_TIMEOUT},
        },
    }


class ToolCallTimeoutPolicyPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-call-timeout-policy`: Cooperative tool execution timeout enforcer.
    """

    id = "timeout-policy"
    name = "@deepseek-ai/dsh-tool-call-timeout-policy"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools_svc = ctx.get("tools") if ctx.has("tools") else None
        if not tools_svc:
            return

        async def on_execute(exec_data: Any, next_fn: Any) -> Any:
            tool_name = exec_data.get("name") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
            agent = exec_data.get("agent") if isinstance(exec_data, dict) else getattr(exec_data, "agent", None)
            
            tool_def = tools_svc.get(tool_name, agent) if hasattr(tools_svc, "get") else None
            timeout_ms = getattr(tool_def, "timeoutMs", getattr(tool_def, "timeout_ms", None)) if tool_def else None

            if timeout_ms is None or timeout_ms <= 0:
                return await next_fn()

            timeout_sec = timeout_ms / 1000.0
            try:
                return await asyncio.wait_for(next_fn(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                return tool_timeout_result(timeout_ms)

        ctx.on("tools/execute", on_execute)
