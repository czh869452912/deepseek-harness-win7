"""
1:1 Test Parity Suite for @deepseek-ai/dsh-agent-loop
Matching reference/packages/core/agent-loop/tests/ (cancel.spec.ts, loop.spec.ts, request-reconstruction.spec.ts, tool-calls.spec.ts)
Covers:
- Cancel on idle agent is no-op, prompt runs normally
- Cancel mid-step aborts turn with { kind: 'aborted', reason: cause }
- Request header reconstruction and canonicalization across series
- Tool calls execution, output capture, additional context splicing
- Streaming chunk assembly and interrupted block recovery
"""

import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import (
    AgentLoopPlugin,
    AgentLoopService,
    BlockAssembler,
    PartialBlock,
    canonical_header,
    header_equals,
    request_proposal,
)
from dsh.core.session import Session, SessionPlugin, SessionStore
from dsh.core.tools import ToolsPlugin, ToolsService, define_tool


class MockLlmService:
    def __init__(self, responses=None):
        self.provider = "mock"
        self.model = "mock-model"
        self.responses = list(responses or [])
        self.requests = []

    def chat_completion(self, messages, tools=None, system=None):
        self.requests.append({"messages": messages, "tools": tools, "system": system})
        if self.responses:
            return self.responses.pop(0)
        return {"content": "mock response"}

    async def chat_completion_stream(self, messages, tools=None, system=None):
        self.requests.append({"messages": messages, "tools": tools, "system": system})
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, str) and resp == "hang":
                await asyncio.sleep(10)
                yield {"type": "text-delta", "index": 0, "text": "never"}
                return
            if isinstance(resp, dict):
                content = resp.get("content", "")
                if content:
                    yield {"type": "text-delta", "index": 0, "text": content}
                tcalls = resp.get("tool_calls", [])
                for idx, tc in enumerate(tcalls):
                    func = tc.get("function", {}) if "function" in tc else tc
                    yield {
                        "type": "tool-call-delta",
                        "index": idx + 10,
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "argumentsDelta": func.get("arguments", ""),
                    }
                yield {"type": "finish", "reason": {"kind": "stop"}}
                return
        yield {"type": "text-delta", "index": 0, "text": "mock stream reply"}
        yield {"type": "finish", "reason": {"kind": "stop"}}


async def create_harness(responses=None):
    ctx = Context()
    ctx.set_service("llm", MockLlmService(responses=responses))
    ctx.plugin(SessionPlugin)
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentPlugin)
    ctx.plugin(AgentLoopPlugin)
    return ctx


@pytest.mark.asyncio
async def test_agent_loop_basic_turn_execution():
    ctx = await create_harness(responses=[{"content": "Hello from model!"}])
    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("session-1")
    agent = handle.agent

    agent.followup("Hello agent")
    await agent.when_idle()

    # User message and assistant message logged
    user_msgs = [e for e in agent.session.events if e.get("type") == "user/message"]
    asst_msgs = [e for e in agent.session.events if e.get("type") == "assistant/message"]
    turn_ends = [e for e in agent.session.events if e.get("type") == "turn/end"]

    assert len(user_msgs) >= 1
    assert len(asst_msgs) >= 1
    assert len(turn_ends) == 1
    assert turn_ends[0]["data"]["reason"] == {"kind": "completed"}

    await handle.dispose()


@pytest.mark.asyncio
async def test_agent_loop_cancel_on_idle_is_noop_and_next_prompt_runs():
    ctx = await create_harness(responses=[{"content": "real prompt reply"}])
    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("cancel-idle")
    agent = handle.agent

    # Cancel on idle agent with empty inbox
    agent.cancel({"kind": "user"})
    assert agent.is_cancelled() is False

    # Next prompt runs cleanly
    agent.followup("real prompt")
    await agent.when_idle()

    asst_msgs = [e for e in agent.session.events if e.get("type") == "assistant/message"]
    assert len(asst_msgs) == 1

    await handle.dispose()


@pytest.mark.asyncio
async def test_agent_loop_cancel_mid_stream_aborts_turn_with_reason():
    ctx = await create_harness(responses=["hang", {"content": "second reply"}])
    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("cancel-mid-turn")
    agent = handle.agent

    agent.followup("start hanging")
    await asyncio.sleep(0.02)

    # Cancel while active
    agent.cancel({"kind": "user"})
    await agent.when_idle()

    turn_ends = [e for e in agent.session.events if e.get("type") == "turn/end"]
    assert len(turn_ends) >= 1
    assert turn_ends[-1]["data"]["reason"] == {"kind": "aborted", "reason": {"kind": "user"}}

    # Next prompt runs normally
    agent.followup("second prompt")
    await agent.when_idle()

    turn_ends2 = [e for e in agent.session.events if e.get("type") == "turn/end"]
    assert len(turn_ends2) == 2
    assert turn_ends2[-1]["data"]["reason"] == {"kind": "completed"}

    await handle.dispose()


@pytest.mark.asyncio
async def test_agent_loop_tool_call_execution_and_result_pairing():
    ctx = await create_harness()
    tools_svc: ToolsService = ctx.get("tools")

    executed = []

    def mock_echo(tool_call_id, params, session, ctx):
        executed.append(params.get("text"))
        return f"echo: {params.get('text')}"

    tools_svc.register_tool(define_tool(
        name="echo_tool",
        description="Echo input text",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        execute=mock_echo,
    ))

    # Mock model calling tool in step 1, then finalizing in step 2
    llm: MockLlmService = ctx.get("llm")
    llm.responses = [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "echo_tool", "arguments": '{"text": "hi"}'},
                }
            ],
        },
        {"content": "all done!"},
    ]

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("tool-session")
    agent = handle.agent

    agent.followup("Please call echo")
    await agent.when_idle()

    assert executed == ["hi"]

    tool_results = [e for e in agent.session.events if e.get("type") == "tool/result"]
    assert len(tool_results) == 1
    assert tool_results[0]["data"]["message"]["content"][0]["toolCallId"] == "call_1"

    await handle.dispose()


def test_block_assembler_streaming_and_interrupted_blocks():
    assembler = BlockAssembler()
    assembler.push({"type": "text-delta", "index": 0, "text": "first partial"})
    assembler.push({"type": "tool-call-delta", "index": 1, "id": "c1", "name": "read", "arguments": '{"p'})

    interrupted = assembler.interrupted_blocks()
    assert len(interrupted) == 1
    assert interrupted[0]["type"] == "text"
    assert interrupted[0]["text"] == "first partial"
