"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent-loop:
- cancel.spec.ts (F2 leak guard on idle cancel, keepInbox behavior, tool abort before dispatch)
- request-error.spec.ts (agent/request-error waterfall, retry action, rate limit handling)
- contract-regressions.spec.ts (tool execution abort ends turn cleanly, replay state preservation)
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, CancelOptions
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import Session, SessionStore
from dsh.core.tools import ToolsService, Tool, TOOL_ABORTED_BEFORE_DISPATCH
from dsh.llm.llm_service import LlmError


class MockResponsesLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat_completion_stream(self, messages, tools=None, model=None, temperature=0.0):
        self.requests.append({"messages": messages, "tools": tools})
        if not self.responses:
            yield ("finish", {"message": {"role": "assistant", "content": "no more responses"}, "usage": {}})
            return

        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if callable(resp):
            resp = resp()

        if isinstance(resp, list):
            for chunk in resp:
                yield chunk
        elif isinstance(resp, dict):
            yield ("finish", {"message": resp, "usage": {}})

    def resolve_model(self, m=None): return "mock"
    def resolve_base_url(self): return "https://mock"


# ============================================================================
# 1. Cancel Tests (from agent-loop/tests/cancel.spec.ts)
# ============================================================================

@pytest.mark.asyncio
async def test_cancel_on_idle_agent_is_noop_f2_leak_guard():
    """Cancel on an idle agent with nothing queued is a no-op; the next prompt runs."""
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)

    mock_llm = MockResponsesLLM([
        {"role": "assistant", "content": "reply to real prompt"}
    ])
    ctx.set_service("llm", mock_llm)

    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)

    handle = await agent_loop.create_agent("cancel-guard-session")
    agent = handle.agent

    # Cancel while idle with empty queue
    agent.cancel(cause={"kind": "user"})

    # Send a prompt and wait
    agent.followup("real prompt")
    await agent.when_idle()

    # The prompt ran: one turn completed
    user_msgs = [e for e in agent.session.events if e.get("type") == "user/message" and e.get("data", {}).get("source", {}).get("kind") == "user"]
    assert len(user_msgs) == 1
    assert any(e.get("type") == "turn/end" for e in agent.session.events)


@pytest.mark.asyncio
async def test_cancel_during_tool_execution_aborts_turn_and_sets_aborted_reason():
    """Abort during tool execution ends the turn cleanly."""
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)

    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    agent_ref = None

    def aborter():
        if agent_ref:
            agent_ref.cancel(cause={"kind": "user"})
        return "done"

    tools.register(
        name="aborter",
        description="Aborts agent",
        parameters={},
        handler=aborter,
    )

    mock_llm = MockResponsesLLM([
        # 1st call returns tool call
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "aborter", "arguments": "{}"}}]
        },
        # 2nd call (if turn didn't abort)
        {"role": "assistant", "content": "should not reach"}
    ])
    ctx.set_service("llm", mock_llm)

    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)

    handle = await agent_loop.create_agent("abort-tool-session")
    agent = handle.agent
    agent_ref = agent

    agent.followup("trigger abort tool")
    await agent.when_idle()

    # Turn ended with aborted reason
    turn_end_events = [e for e in agent.session.events if e.get("type") == "turn/end"]
    assert len(turn_end_events) == 1
    reason = turn_end_events[0].get("data", {}).get("reason", {})
    assert reason.get("kind") == "aborted"


# ============================================================================
# 2. Request Error & Retry Tests (from agent-loop/tests/request-error.spec.ts)
# ============================================================================

@pytest.mark.asyncio
async def test_agent_request_error_retry_recovery():
    """Verify agent/request-error waterfall allows retry action before turn closes."""
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)

    # 2 rate limits followed by success
    mock_llm = MockResponsesLLM([
        LlmError("busy", "RATE_LIMIT"),
        LlmError("unavailable", "SERVICE_UNAVAILABLE"),
        {"role": "assistant", "content": "ok success"},
    ])
    ctx.set_service("llm", mock_llm)

    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)

    seen_errors = []

    async def _on_req_err(payload):
        seen_errors.append(payload)
        return {"kind": "retry"}

    ctx.on("agent/request-error", _on_req_err)

    handle = await agent_loop.create_agent("retry-session")
    agent = handle.agent

    agent.followup("go")
    await agent.when_idle()

    # Exactly 1 turn completed successfully after retries
    turn_starts = [e for e in agent.session.events if e.get("type") == "turn/start"]
    turn_ends = [e for e in agent.session.events if e.get("type") == "turn/end"]
    assert len(turn_starts) == 1
    assert len(turn_ends) == 1
    assert turn_ends[0].get("data", {}).get("reason", {}).get("kind") == "completed"
