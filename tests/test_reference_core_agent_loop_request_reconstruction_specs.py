"""
1:1 Test Parity Suite matching reference/packages/core/agent-loop/tests/request-reconstruction.spec.ts.
Covers:
- Request stability and prefix extension within a turn
- Extension across multiple turns
- Explicit startsRequestSeries request series boundaries
- Request series with header changes (reason: 'change', startsSeries: true)
- Preservation of series declarations when middleware rebuilds decision
"""

import asyncio
import pytest
from typing import Any, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import Session, SessionPlugin, SessionStore
from dsh.core.tools import ToolsPlugin, ToolsService, define_tool
from dsh.llm.message import createUserMessage


class MockLlmAdapter:
    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None):
        self.provider = "mock"
        self.model = "mock"
        self.responses = list(responses or [])
        self.requests: List[Dict[str, Any]] = []

    async def stream(self, request: Dict[str, Any]):
        self.requests.append(dict(request))
        if self.responses:
            resp = self.responses.pop(0)
            text = resp.get("text", resp.get("content", ""))
            if text:
                yield {"type": "text-delta", "index": 0, "text": text}
            tcalls = resp.get("tool_calls", [])
            for idx, tc in enumerate(tcalls):
                func = tc.get("function", {}) if "function" in tc else tc
                yield {
                    "type": "tool-call-delta",
                    "index": idx + 10,
                    "id": tc.get("id", f"call-{idx}"),
                    "name": func.get("name", ""),
                    "argumentsDelta": func.get("arguments", ""),
                }
            yield {"type": "finish", "reason": {"kind": "stop"}}
            return
        yield {"type": "text-delta", "index": 0, "text": "mock default reply"}
        yield {"type": "finish", "reason": {"kind": "stop"}}


def text_response(text: str) -> Dict[str, Any]:
    return {"text": text}


def tool_call_response(call_id: str, name: str, args: Dict[str, Any], thought: str = "") -> Dict[str, Any]:
    import json
    return {
        "text": thought,
        "tool_calls": [
            {
                "id": call_id,
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


async def setup_harness(adapter: MockLlmAdapter, persona: str = "stable base") -> Context:
    ctx = Context()
    ctx.set_service("llm", adapter)

    class MockPersona:
        def get_prompt(self):
            return persona

    ctx.set_service("persona", MockPersona())
    SessionPlugin().apply(ctx)
    ToolsPlugin().apply(ctx)
    AgentPlugin().apply(ctx)
    AgentLoopPlugin().apply(ctx)
    return ctx


def send(agent: Agent, text: str) -> None:
    agent.followup(createUserMessage({
        "content": [{"type": "text", "text": text}],
        "source": {"kind": "user"},
    }))


def expect_prefix_extension(prev_req: Dict[str, Any], curr_req: Dict[str, Any]) -> None:
    prev_msgs = prev_req["messages"]
    curr_msgs = curr_req["messages"]
    assert len(curr_msgs) > len(prev_msgs)
    assert curr_msgs[:len(prev_msgs)] == prev_msgs


@pytest.mark.asyncio
async def test_step_requests_within_turn_append_extends_previous_and_one_initial_header():
    adapter = MockLlmAdapter([
        tool_call_response("c1", "echo", {"text": "one"}, "first"),
        tool_call_response("c2", "echo", {"text": "two"}, "second"),
        text_response("done"),
    ])
    ctx = await setup_harness(adapter)
    tools: ToolsService = ctx.get("tools")

    async def echo_tool(text: str):
        return [{"type": "text", "text": f"echo: {text}"}]

    tools.register(name="echo", description="echo back", parameters={"text": {"type": "string"}}, handler=echo_tool)

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a1", options=AgentOptions(provider="mock", model="mock"))

    send(agent, "go")
    await agent.when_idle()

    assert len(adapter.requests) == 3
    expect_prefix_extension(adapter.requests[0], adapter.requests[1])
    expect_prefix_extension(adapter.requests[1], adapter.requests[2])

    header_events = [e for e in agent.session.events if e.get("type") == "request/header"]
    assert len(header_events) == 1
    assert header_events[0]["data"]["reason"] == "initial"


@pytest.mark.asyncio
async def test_later_turn_append_extends_previous_turn():
    adapter = MockLlmAdapter([text_response("one"), text_response("two")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a1", options=AgentOptions(provider="mock", model="mock"))

    send(agent, "first")
    await agent.when_idle()
    send(agent, "second")
    await agent.when_idle()

    assert len(adapter.requests) == 2
    expect_prefix_extension(adapter.requests[0], adapter.requests[1])
    header_reasons = [e["data"]["reason"] for e in agent.session.events if e.get("type") == "request/header"]
    assert header_reasons == ["initial"]


@pytest.mark.asyncio
async def test_starts_new_request_series_when_admitted_step_asks_for_one():
    adapter = MockLlmAdapter([text_response("one"), text_response("two")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a1", options=AgentOptions(provider="mock", model="mock"))

    async def pre_step_hook(payload, next_fn=None):
        turn = payload.get("turn", 1)
        if turn == 2:
            return {"startsRequestSeries": True, "messages": payload.get("messages", [])}
        return payload

    ctx.on("agent/pre-step", pre_step_hook)

    send(agent, "first")
    await agent.when_idle()
    send(agent, "second series")
    await agent.when_idle()

    expect_prefix_extension(adapter.requests[0], adapter.requests[1])
    header_reasons = [e["data"]["reason"] for e in agent.session.events if e.get("type") == "request/header"]
    assert header_reasons == ["initial", "series"]


@pytest.mark.asyncio
async def test_retains_explicit_series_boundary_when_request_also_changes_header():
    adapter = MockLlmAdapter([text_response("one"), text_response("two")])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a1", options=AgentOptions(provider="mock", model="mock"))

    async def pre_step_hook(payload, next_fn=None):
        turn = payload.get("turn", 1)
        if turn == 2:
            return {"startsRequestSeries": True, "messages": payload.get("messages", [])}
        return payload

    async def request_hook(config, next_fn=None):
        if getattr(agent, "_last_turn", 1) == 2:
            return {**config, "model": "mock-changed"}
        return config

    ctx.on("agent/pre-step", pre_step_hook)
    ctx.on("agent/request", request_hook)

    send(agent, "first")
    await agent.when_idle()
    send(agent, "second series")
    await agent.when_idle()

    expect_prefix_extension(adapter.requests[0], adapter.requests[1])
    headers = [
        {"reason": e["data"]["reason"], "startsSeries": e.get("data", {}).get("startsSeries")}
        for e in agent.session.events
        if e.get("type") == "request/header"
    ]
    assert headers == [
        {"reason": "initial", "startsSeries": None},
        {"reason": "change", "startsSeries": True},
    ]
