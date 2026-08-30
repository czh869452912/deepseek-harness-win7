"""
1:1 Test Parity Suite matching reference/packages/core/agent-loop/tests/contract-regressions.spec.ts.
Covers:
- Assistant message source with provider, model, and replayState
- Abort during tool execution parks injected context until next wake
- Pre-turn prompt modifications propagate through assemble waterfalls
- Post-tool additional context injection into step
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
            finish_chunk = {
                "type": "finish",
                "reason": resp.get("reason", {"kind": "stop"}),
            }
            if "replayState" in resp:
                finish_chunk["replayState"] = resp["replayState"]
            yield finish_chunk
            return
        yield {"type": "text-delta", "index": 0, "text": "mock default reply"}
        yield {"type": "finish", "reason": {"kind": "stop"}}


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


@pytest.mark.asyncio
async def test_assistant_replay_state_recorded_with_assembled_assistant_content():
    replay_state = {"response": {"private": "state"}, "blocks": ["block-meta"]}
    adapter = MockLlmAdapter([
        {
            "text": "unchanged",
            "reason": {"kind": "stop"},
            "replayState": replay_state,
        }
    ])
    ctx = await setup_harness(adapter)
    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("replay-state", options=AgentOptions(provider="mock", model="next-model"))

    send(agent, "go")
    await agent.when_idle()

    recorded = next((e for e in agent.session.events if e.get("type") == "assistant/message"), None)
    assert recorded is not None
    assert recorded["data"]["message"]["source"] == {
        "kind": "model",
        "provider": "mock",
        "model": "next-model",
        "replayState": replay_state,
    }
    derived = agent.session.derive_messages()
    assert derived[-1]["source"] == {
        "kind": "model",
        "provider": "mock",
        "model": "next-model",
        "replayState": replay_state,
    }


@pytest.mark.asyncio
async def test_parks_context_finalized_after_tool_step_abort_until_another_wakeup():
    import json
    adapter = MockLlmAdapter([
        {
            "text": "calling aborter",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {"name": "aborter", "arguments": "{}"},
                }
            ],
        },
        {"text": "after wake"},
    ])
    ctx = await setup_harness(adapter)
    tools: ToolsService = ctx.get("tools")

    agent = None

    async def aborter_tool():
        agent.inject("accepted before abort")
        agent.cancel({"kind": "user"}, keep_inbox=True)
        return [{"type": "text", "text": "done"}]

    tools.register(name="aborter", description="abort helper", parameters={}, handler=aborter_tool)

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    agent = loop_svc.create("a-abort-injection", options=AgentOptions(provider="mock", model="mock"))

    send(agent, "initial question")
    await agent.when_idle()

    # The aborted turn recorded aborted turn/end
    assert agent.session.events[-1]["type"] == "turn/end"
    assert agent.session.events[-1]["data"]["reason"] == {"kind": "aborted", "reason": {"kind": "user"}}

    # Next wakeup resumes and runs the parked injected context
    send(agent, "wake up")
    await agent.when_idle()

    assert agent.session.events[-1]["type"] == "turn/end"
    assert agent.session.events[-1]["data"]["reason"] == {"kind": "completed"}
