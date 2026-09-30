"""
Cooperative tool-call timeout enforcer (`@deepseek-ai/dsh-tool-call-timeout-policy`).
"""

from typing import Any, Dict
from dsh.cordis.plugin import Plugin
from dsh.core.timeout import deadline, timeout_of, _number_text
from dsh.core.tools import ToolExecutionResult

TOOL_TIMEOUT = "TOOL_TIMEOUT"


def tool_timeout_result(timeout_ms: int) -> Dict[str, Any]:
    message = "tool call timed out after {}ms".format(_number_text(timeout_ms))
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
        async def on_execute(exec_data: Any, next_fn: Any) -> Any:
            tool_name = exec_data.get("name") if isinstance(exec_data, dict) else getattr(exec_data, "name", "")
            agent = exec_data.get("agent") if isinstance(exec_data, dict) else getattr(exec_data, "agent", None)
            
            tool_def = ctx.get("tools").get(tool_name, agent)
            timeout_ms = getattr(tool_def, "timeoutMs", getattr(tool_def, "timeout_ms", None)) if tool_def else None

            if timeout_ms is None:
                return await next_fn()

            upstream = exec_data.get("signal") if isinstance(exec_data, dict) else exec_data.signal
            d = deadline(upstream, timeout_ms, TOOL_TIMEOUT)
            if isinstance(exec_data, dict):
                exec_data["signal"] = d.signal
            else:
                exec_data.signal = d.signal
            try:
                result = await next_fn()
                if timeout_of(d.signal, TOOL_TIMEOUT) is not None:
                    failure = tool_timeout_result(timeout_ms)
                    return ToolExecutionResult(failure["content"], is_error=True, error=failure["error"])
                return result
            finally:
                if isinstance(exec_data, dict):
                    exec_data["signal"] = upstream
                else:
                    exec_data.signal = upstream
                d.dispose()

        ctx.on("tools/execute", on_execute)
