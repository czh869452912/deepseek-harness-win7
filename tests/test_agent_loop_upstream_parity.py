import pytest

from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.agent_loop import AgentLoopService
from dsh.core.session import Session


class _Llm:
    def __init__(self):
        self.called = 0

    def chat_completion_stream(self, **kwargs):
        self.called += 1
        yield {"type": "block-start", "index": 0, "blockType": "text"}
        yield {"type": "text-delta", "index": 0, "text": "from adapter"}
        yield {"type": "block-end", "index": 0, "block": {"type": "text", "text": "from adapter"}}
        yield {"type": "finish", "reason": {"kind": "stop"}}


@pytest.mark.asyncio
async def test_agent_loop_routes_stream_through_waterfall():
    ctx = Context()
    llm = _Llm()
    ctx.set_service("llm", llm)
    session = Session.create("agent-loop-parity", ctx=ctx)
    agent = Agent(session=session, options=AgentOptions(provider="p", model="m"), ctx=ctx)
    agent.inbox.append("next-step", {"role": "user", "content": "hello"})
    seen = []

    async def intercept(options, next_fn):
        seen.append(options)
        return await next_fn()

    ctx.on("llm/stream", intercept)
    service = AgentLoopService(ctx)
    result = await service._step(agent, 1, 1, "system")

    assert result == {"kind": "completed"}
    assert llm.called == 1
    assert seen and seen[0]["provider"] == "p"
    assert seen[0]["model"] == "m"
    assert seen[0]["sessionId"] == session.id
    assert any(e["type"] == "assistant/message" for e in session.events)


@pytest.mark.asyncio
async def test_agent_request_waterfall_preserves_explicit_config():
    ctx = Context()
    llm = _Llm()
    ctx.set_service("llm", llm)
    session = Session.create("agent-request-parity", ctx=ctx)
    agent = Agent(session=session, options=AgentOptions(provider="p", model="m", max_tokens=123), ctx=ctx)
    seen = []

    async def request_hook(payload, next_fn):
        seen.append(payload)
        value = await next_fn()
        value["reasoningEffort"] = "high"
        return value

    ctx.on("agent/request", request_hook)
    service = AgentLoopService(ctx)
    agent.inbox.append("next-step", {"role": "user", "content": "hello"})
    await service._step(agent, 1, 1, "system")

    assert seen and seen[0]["turn"] == 1 and seen[0]["step"] == 1
    header = session.request_header()
    assert header["config"]["maxTokens"] == 123
    assert header["config"]["reasoningEffort"] == "high"
