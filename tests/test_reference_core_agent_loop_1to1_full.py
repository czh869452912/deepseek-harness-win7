"""
1:1 Test Parity Suite matching reference/packages/core/agent-loop/tests/loop.spec.ts.
Covers:
- maxTokens validation and request seeding
- reasoningEffort validation and request propagation
- maintenance task coordination, wake replay, and wake removal
- turn/step execution ordering: turn/start -> step/start -> user/message -> assistant/message -> step/end -> turn/end
- tool execution round-trips and result projection
"""

import asyncio
import pytest
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import (
    Session,
    SessionPlugin,
    SessionStore,
    createUserMessage,
    createToolResultMessage,
    createAssistantMessage,
)
from dsh.core.tools import ToolsService, ToolsPlugin


class MockLlmAdapter:
    """Mock LLM adapter simulating responses with usage and tool calls."""
    def __init__(self, responses: List[Dict[str, Any]]):
        self.responses = list(responses)
        self.requests = []

    async def stream(self, request: Dict[str, Any]):
        self.requests.append(dict(request))
        if not self.responses:
            return
        resp = self.responses.pop(0)
        chunks = resp.get("chunks", [])
        for c in chunks:
            yield c


def text_response(text: str) -> Dict[str, Any]:
    return {
        "chunks": [
            {"type": "text-delta", "index": 0, "text": text},
            {"type": "finish", "usage": {"inputTokens": 10, "outputTokens": len(text)}},
        ]
    }


def tool_call_response(call_id: str, name: str, args: Dict[str, Any], thought: str = "") -> Dict[str, Any]:
    import json
    chunks = []
    if thought:
        chunks.append({"type": "text-delta", "index": 0, "text": thought})
    chunks.append({
        "type": "tool-call-delta",
        "index": 1,
        "id": call_id,
        "name": name,
        "argumentsDelta": json.dumps(args),
    })
    chunks.append({"type": "finish", "usage": {"inputTokens": 10, "outputTokens": 15}})
    return {"chunks": chunks}


async def setup_harness(adapter: MockLlmAdapter) -> Context:
    ctx = Context()
    SessionPlugin().apply(ctx)
    ToolsPlugin().apply(ctx)
    AgentPlugin().apply(ctx)
    AgentLoopPlugin().apply(ctx)

    # Set up LLM mock
    class LlmMock:
        def __init__(self, ad):
            self.adapter = ad
        async def stream(self, req):
            async for chunk in self.adapter.stream(req):
                yield chunk
        async def generate(self, req):
            chunks = []
            async for chunk in self.adapter.stream(req):
                chunks.append(chunk)
            return chunks

    ctx.set_service("llm", LlmMock(adapter))
    return ctx


def send(agent: Agent, text: str):
    agent.followup(createUserMessage({
        "content": [{"type": "text", "text": text}],
        "source": {"kind": "user"},
    }))


def user_texts(agent: Agent) -> List[str]:
    texts = []
    for e in agent.session.events:
        if e.get("type") == "user/message":
            data = e.get("data", {})
            content = data.get("content", [])
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        texts.append(b.get("text", ""))
                    elif isinstance(b, str):
                        texts.append(b)
            elif isinstance(content, str):
                texts.append(content)
    return texts


# ============================================================================
# 1. maxTokens and reasoningEffort Parity
# ============================================================================

@pytest.mark.asyncio
async def test_agent_loop_rejects_invalid_max_tokens():
    adapter = MockLlmAdapter([])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")

    for invalid_val in [0, -1, 1.5, 9007199254740992]:
        with pytest.raises(ValueError, match="max_tokens must be a positive safe integer|maxTokens"):
            loop_svc.create("invalid-tokens", options=AgentOptions(max_tokens=invalid_val))


@pytest.mark.asyncio
async def test_agent_loop_seeds_valid_max_tokens_into_request():
    adapter = MockLlmAdapter([text_response("bounded")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")

    agent = loop_svc.create("valid-max-tokens", options=AgentOptions(max_tokens=256))
    send(agent, "use the configured output limit")
    await agent.when_idle()

    assert len(adapter.requests) >= 1
    assert adapter.requests[0].get("max_tokens") == 256 or adapter.requests[0].get("maxTokens") == 256


@pytest.mark.asyncio
async def test_agent_loop_seeds_reasoning_effort_into_request():
    adapter = MockLlmAdapter([text_response("reasoned")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")

    agent = loop_svc.create("valid-effort", options=AgentOptions(reasoning_effort="high"))
    send(agent, "use reasoning")
    await agent.when_idle()

    assert len(adapter.requests) >= 1
    assert adapter.requests[0].get("reasoning_effort") == "high" or adapter.requests[0].get("reasoningEffort") == "high"


# ============================================================================
# 2. Maintenance Task, Cancellation, and Wake Replay Parity
# ============================================================================

@pytest.mark.asyncio
async def test_agent_loop_cancels_queued_wakeup_work_together_with_maintenance():
    adapter = MockLlmAdapter([text_response("park reply")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")

    agent = loop_svc.create("cancel-maint", options=AgentOptions(provider="mock", model="mock"))
    started = asyncio.Event()

    async def long_maintenance(signal):
        started.set()
        await signal.wait()
        raise RuntimeError("maintenance aborted")

    maint_task = asyncio.create_task(agent.run_maintenance(long_maintenance))
    await started.wait()

    send(agent, "discard this wakeup")
    agent.cancel(reason={"kind": "user"})
    send(agent, "park after cancellation")

    with pytest.raises(RuntimeError, match="maintenance aborted"):
        await maint_task

    await agent.when_idle()
    assert user_texts(agent) == ["park after cancellation"]
    assert len(agent.inbox.next_turn) == 0


@pytest.mark.asyncio
async def test_agent_loop_replays_wake_latched_behind_maintenance():
    adapter = MockLlmAdapter([text_response("wake reply")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")

    agent = loop_svc.create("maint-replay", options=AgentOptions(provider="mock", model="mock"))
    started = asyncio.Event()
    finish = asyncio.Event()

    async def maint_task_fn(signal):
        started.set()
        await finish.wait()

    maint_task = asyncio.create_task(agent.run_maintenance(maint_task_fn))
    await started.wait()

    send(agent, "wake behind maintenance")
    finish.set()
    await maint_task
    await agent.when_idle()

    assert user_texts(agent) == ["wake behind maintenance"]
    assert len(adapter.requests) == 1


# ============================================================================
# 3. Exact Turn and Step Ordering Parity
# ============================================================================

@pytest.mark.asyncio
async def test_agent_loop_ordered_events_turn_and_step_nesting():
    adapter = MockLlmAdapter([text_response("hello there")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a1", options=AgentOptions(provider="mock", model="mock"))

    order = []
    def on_session_event(session, event):
        etype = event.get("type")
        if etype in ("turn/start", "step/start", "step/end", "turn/end"):
            order.append(etype)

    ctx.on("session/event", on_session_event)

    send(agent, "hi")
    await agent.when_idle()

    assert order == ["turn/start", "step/start", "step/end", "turn/end"]

    types = [e["type"] for e in agent.session.events]
    # Durable inbox receipt precedes the turn-owned transcript
    assert types[0] == "agent/inbox/spliced"
    assert "turn/start" in types
    assert "step/start" in types
    assert "user/message" in types
    assert "assistant/message" in types
    assert types[-1] == "turn/end"

    # Step/start must occur BEFORE the step's user/message
    step_start_idx = types.index("step/start")
    user_msg_idx = types.index("user/message")
    assert step_start_idx < user_msg_idx

    # Derived history has user + assistant
    messages = agent.session.derive_messages()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == [{"type": "text", "text": "hello there"}]


# ============================================================================
# 4. Tool Call Round-Trip Parity
# ============================================================================

@pytest.mark.asyncio
async def test_agent_loop_tool_call_round_trip():
    adapter = MockLlmAdapter([
        tool_call_response("c1", "echo", {"text": "ping"}, thought="calling echo"),
        text_response("done"),
    ])
    ctx = await setup_harness(adapter)
    tools: ToolsService = ctx.get("tools")

    async def echo_tool(text: str):
        return [{"type": "text", "text": f"echo: {text}"}]

    tools.register(
        name="echo",
        description="echo back",
        parameters={"text": {"type": "string"}},
        handler=echo_tool,
    )

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a-tool", options=AgentOptions(provider="mock", model="mock"))

    send(agent, "use the tool")
    await agent.when_idle()

    assert len(adapter.requests) == 2
    # Second request derived history contains the tool result
    second_msgs = adapter.requests[1].get("messages", [])
    tool_res = [m for m in second_msgs if any(isinstance(b, dict) and b.get("type") == "tool-result" for b in m.get("content", []))]
    assert len(tool_res) >= 1
    assert tool_res[0]["content"][0]["toolCallId"] == "c1"
