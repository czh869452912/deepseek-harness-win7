"""
Tests for canonical agent loop interception hooks: agent/pre-step, agent/session-start,
tools/pre-execute, and tools/post-execute matching reference/packages/core/agent-loop/tests/interception.spec.ts.
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import Session, SessionStore
from dsh.core.tools import ToolsPlugin, ToolsService


class MockLLMService:
    def __init__(self, responses=None):
        self.responses = list(responses or ["done"])
        self.requests = []
        self.provider = "mock"
        self.model = "mock"

    async def chat_completion(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        resp = self.responses.pop(0) if self.responses else "ok"
        return {"content": resp, "role": "assistant"}

    async def chat_completion_stream(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        resp = self.responses.pop(0) if self.responses else "ok"
        yield {
            "choices": [
                {
                    "delta": {"content": resp, "role": "assistant"},
                    "finish_reason": "stop"
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }


@pytest.mark.asyncio
async def test_session_start_hook_fires_and_seeds_preamble():
    """agent/session-start fires on startup and allows seeding context."""
    ctx = Context()
    ctx.set_service("llm", MockLLMService(["hello from assistant"]))
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentLoopPlugin)

    session_start_sources = []
    def on_session_start(data):
        session_start_sources.append(data.get("source"))
        agent = data.get("agent")
        if agent:
            agent.inbox.inject({"content": "system preamble text", "source": {"kind": "plugin", "plugin": "test"}})

    ctx.on("agent/session-start", on_session_start)

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    handle = await loop_svc.create("test-session-start")
    agent = handle.agent

    assert session_start_sources == ["startup"]

    # Followup with user message
    agent.followup({"content": "user prompt", "source": {"kind": "user"}})
    await agent.when_idle()

    # Verify that the preamble and prompt were sent to the LLM
    llm = ctx.get("llm")
    assert len(llm.requests) > 0
    all_msgs = [m.get("content") for m in llm.requests[0]["messages"]]
    assert any("system preamble text" in str(m) for m in all_msgs)
    assert any("user prompt" in str(m) for m in all_msgs)

    await handle.dispose()


@pytest.mark.asyncio
async def test_pre_step_hook_prompt_rewrite():
    """agent/pre-step can rewrite prompt before recording into session."""
    ctx = Context()
    ctx.set_service("llm", MockLLMService(["rewritten response"]))
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentLoopPlugin)

    async def on_pre_step(data, next_fn):
        messages = data.get("messages", [])
        rewritten = [{"content": "REWRITTEN_PROMPT", "source": {"kind": "user"}}]
        return {"kind": "enter", "messages": rewritten}

    ctx.on("agent/pre-step", on_pre_step)

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    handle = await loop_svc.create("test-pre-step-rewrite")
    agent = handle.agent

    agent.followup({"content": "original_prompt", "source": {"kind": "user"}})
    await agent.when_idle()

    llm = ctx.get("llm")
    assert len(llm.requests) > 0
    all_msgs = [m.get("content") for m in llm.requests[0]["messages"]]
    assert any("REWRITTEN_PROMPT" in str(m) for m in all_msgs)
    assert not any("original_prompt" in str(m) for m in all_msgs)

    await handle.dispose()


@pytest.mark.asyncio
async def test_pre_step_hook_reject_closes_turn():
    """agent/pre-step reject closes turn with blocked reason and no LLM call."""
    ctx = Context()
    mock_llm = MockLLMService(["should not be called"])
    ctx.set_service("llm", mock_llm)
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentLoopPlugin)

    async def on_pre_step_reject(data, next_fn):
        return {"kind": "reject"}

    ctx.on("agent/pre-step", on_pre_step_reject)

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    handle = await loop_svc.create("test-pre-step-reject")
    agent = handle.agent

    agent.followup({"content": "blocked prompt", "source": {"kind": "user"}})
    await agent.when_idle()

    # LLM should never be called
    assert len(mock_llm.requests) == 0

    # Turn end event recorded with blocked reason
    turn_ends = [e for e in agent.session.events if e.get("type") == "turn/end"]
    assert len(turn_ends) == 1
    assert turn_ends[0]["data"]["reason"] == {"kind": "blocked"}

    await handle.dispose()
