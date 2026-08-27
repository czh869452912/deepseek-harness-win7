"""
Semantic durability checkpoints for model requests, top-level tool dispatch, and completed agent steps.
Aligned 1:1 with official `@deepseek-ai/dsh-session-checkpoint-policy`.
"""

import asyncio
import inspect
from typing import Any, AsyncIterable, Callable, Dict, Optional
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
    # Keep the Loader-visible namespace identical to the TypeScript package.
    inject = ["llm", "sessionPersistence", "sessions", "tools"]

    def apply(self, ctx: Context) -> None:
        def flush_session(session: Any) -> Any:
            sessions = ctx.get("sessions", None, strict=False)
            if sessions is not None and hasattr(sessions, "flush"):
                return sessions.flush(session)
            return session.flush()

        # The Python LLM service exposes chat_completion_stream rather than a
        # separate stream object.  The event is still installed with the
        # canonical (options, next) signature so host runtimes can route their
        # request through the same policy as the TS implementation.
        async def on_llm_stream(options: Dict[str, Any], next_fn: Callable[..., Any]) -> Any:
            if not isinstance(options, dict) or options.get("sessionId") is None:
                result = next_fn()
                return await result if inspect.isawaitable(result) else result
            sessions = ctx.get("sessions", None, strict=False)
            session = sessions.get(options.get("sessionId")) if sessions and hasattr(sessions, "get") else None
            if session is None:
                result = next_fn()
                return await result if inspect.isawaitable(result) else result
            # Return an async generator so downstream construction is lazy.
            async def wrapped() -> AsyncIterable[Any]:
                result = flush_session(session)
                if inspect.isawaitable(result):
                    await result
                result = next_fn()
                if inspect.isawaitable(result):
                    result = await result
                if hasattr(result, "__aiter__"):
                    async for item in result:
                        yield item
            return wrapped()

        async def on_pre_step(*args: Any) -> Any:
            # EventBus supplies (payload, next) for a canonical waterfall and
            # only (next) when a legacy caller omits its terminal callback.
            has_payload = bool(args and isinstance(args[0], dict))
            payload = args[0] if has_payload else {}
            next_fn = args[-1] if args and callable(args[-1]) else None
            agent = payload.get("agent")
            if agent and hasattr(agent, "session"):
                result = flush_session(agent.session)
                if inspect.isawaitable(result):
                    await result
            if has_payload and callable(next_fn):
                result = next_fn()
                return await result if inspect.isawaitable(result) else result
            return None

        async def on_tools_execute(exec_input: Any, next_fn: Callable[..., Any]) -> Any:
            agent = getattr(exec_input, "agent", None)
            parent = getattr(exec_input, "parent", None)
            if agent is not None and parent is None:
                result = flush_session(agent.session)
                if inspect.isawaitable(result):
                    await result
                signal = getattr(exec_input, "signal", None)
                if signal and (
                    (isinstance(signal, asyncio.Event) and signal.is_set())
                    or getattr(signal, "aborted", False)
                ):
                    return aborted_before_dispatch_result()
            if callable(next_fn):
                result = next_fn()
                return await result if inspect.isawaitable(result) else result
            return None

        ctx.on("llm/stream", on_llm_stream)
        ctx.on("agent/pre-step", on_pre_step)
        ctx.on("tools/execute", on_tools_execute)
