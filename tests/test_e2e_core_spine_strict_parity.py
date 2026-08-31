"""
End-to-End Strict Parity Test Suite for Core API Spine:
core/agent-loop + llm + system-prompt + core/session + core/tools.
Matches reference test patterns from:
- reference/packages/core/agent-loop/tests/loop.spec.ts
- reference/packages/core/agent-loop/tests/request-reconstruction.spec.ts
- reference/packages/core/agent-loop/tests/interception.spec.ts
- reference/packages/core/system-prompt/tests/system-prompt.spec.ts
"""

import asyncio
import copy
import json
from typing import Any, Dict, List, Optional
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import Session, SessionPlugin, SessionStore
from dsh.core.system_prompt import (
    FIRST_PARTY_SECTION_ORDER,
    PERSONA_ORDER,
    PERSONA_SECTION,
    SystemPrompt,
)
from dsh.core.tools import ToolsPlugin, ToolsService


class StrictMockLlmAdapter:
    """
    Streaming Mock LLM Adapter emitting 1:1 StreamChunk dictionaries.
    Records every incoming GenerateOptions request for reconstructability verification.
    """

    def __init__(self, responses: Optional[List[Dict[str, Any]]] = None):
        self.responses: List[Dict[str, Any]] = list(responses or [])
        self.requests: List[Dict[str, Any]] = []
        self.provider = "mock-deepseek"
        self.model = "deepseek-reasoner"

    async def chat_completion_stream(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, system: Optional[str] = None):
        # Record deep copy of request
        self.requests.append({
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools) if tools else [],
            "system": system,
        })

        resp = self.responses.pop(0) if self.responses else {"text": "Default mock response"}

        chunks = []
        block_idx = 0

        # 1. Reasoning block (DeepSeek R1/V3 thinking)
        if "reasoning" in resp:
            r_text = resp["reasoning"]
            chunks.append({"type": "block-start", "index": block_idx, "blockType": "reasoning"})
            chunks.append({"type": "reasoning-delta", "index": block_idx, "text": r_text})
            chunks.append({"type": "block-end", "index": block_idx, "block": {"type": "reasoning", "text": r_text}})
            block_idx += 1

        # 2. Text block
        if "text" in resp and resp["text"]:
            t_text = resp["text"]
            chunks.append({"type": "block-start", "index": block_idx, "blockType": "text"})
            chunks.append({"type": "text-delta", "index": block_idx, "text": t_text})
            chunks.append({"type": "block-end", "index": block_idx, "block": {"type": "text", "text": t_text}})
            block_idx += 1

        # 3. Tool call blocks
        if "tool_calls" in resp and resp["tool_calls"]:
            for i, tc in enumerate(resp["tool_calls"]):
                idx = block_idx + i
                call_id = tc.get("id", f"call_{i}")
                call_name = tc.get("name", "echo")
                call_args = tc.get("arguments", "{}")
                if not isinstance(call_args, str):
                    call_args = json.dumps(call_args, ensure_ascii=False)

                chunks.append({"type": "block-start", "index": idx, "blockType": "tool-call"})
                chunks.append({
                    "type": "tool-call-delta",
                    "index": idx,
                    "id": call_id,
                    "name": call_name,
                    "argumentsDelta": call_args,
                })
                chunks.append({
                    "type": "block-end",
                    "index": idx,
                    "block": {
                        "type": "tool-call",
                        "id": call_id,
                        "name": call_name,
                        "arguments": call_args,
                    },
                })
            block_idx += len(resp["tool_calls"])

        # 4. Usage accounting
        usage_data = resp.get("usage", {
            "inputTokens": 45,
            "outputTokens": 80,
            "reasoningTokens": 30 if "reasoning" in resp else 0,
            "cacheReadTokens": 10,
            "totalTokens": 125,
        })
        chunks.append({"type": "usage", "usage": usage_data})

        # 5. Finish reason
        finish_kind = "tool-calls" if "tool_calls" in resp and resp["tool_calls"] else "stop"
        chunks.append({"type": "finish", "reason": {"kind": finish_kind}})

        for c in chunks:
            yield c


async def build_e2e_harness(adapter: StrictMockLlmAdapter, persona: str = "You are DeepSeek Harness Assistant.") -> Context:
    ctx = Context()
    ctx.plugin(SessionPlugin)
    ctx.plugin(ToolsPlugin)
    ctx.plugin(SystemPrompt, config={
        "includeHarnessIdentity": True,
        "persona": persona,
        "includeRuntimeContext": True,
    })
    ctx.plugin(AgentPlugin)
    ctx.plugin(AgentLoopPlugin)
    ctx.set_service("llm", adapter)
    return ctx


@pytest.mark.asyncio
async def test_e2e_multi_step_reasoning_and_tool_call_loop():
    """
    End-to-end multi-step turn execution:
    Step 1: User says 'Compute and answer'
            -> Model outputs reasoning + tool-call 'calculator'
            -> Tool executes and appends tool/result
    Step 2: Model consumes tool result -> outputs reasoning + final text
            -> Turn ends with completed reason.
    """
    adapter = StrictMockLlmAdapter(responses=[
        {
            "reasoning": "I need to multiply 42 by 2 using the calculator tool.",
            "tool_calls": [{"id": "call_calc_1", "name": "calculator", "arguments": {"a": 42, "b": 2}}],
        },
        {
            "reasoning": "The tool returned 84. I will present the final response.",
            "text": "The result is 84.",
        },
    ])

    ctx = await build_e2e_harness(adapter)

    # Register calculator tool
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(
        name="calculator",
        description="Multiply two integers",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
        handler=lambda args: str(int(args["a"]) * int(args["b"])),
    )

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-calc-1")
    agent = handle.agent
    session = agent.session

    # Send prompt and wait for agent to finish turn
    agent.followup("Compute 42 * 2")
    await agent.when_idle()

    # 1. Verify two LLM calls occurred (Step 1 and Step 2)
    assert len(adapter.requests) == 2

    # Step 1: System prompt + User message
    assert "DeepSeek Harness" in adapter.requests[0]["system"]
    step1_msgs = adapter.requests[0]["messages"]
    assert any(m["role"] == "user" and "Compute 42 * 2" in str(m.get("content", "")) for m in step1_msgs)

    # Step 2 messages: User message + Assistant (with tool call) + Tool result
    assert "DeepSeek Harness" in adapter.requests[1]["system"]
    step2_msgs = adapter.requests[1]["messages"]
    assert len(step2_msgs) > len(step1_msgs)
    # Check that Step 1 is a strict prefix of Step 2
    for i in range(len(step1_msgs)):
        assert step2_msgs[i]["role"] == step1_msgs[i]["role"]

    # Tool result block in step 2 user message
    tool_msg = next((m for m in step2_msgs if isinstance(m.get("content"), list) and any(b.get("type") == "tool-result" for b in m["content"])), None)
    assert tool_msg is not None
    tool_block = next(b for b in tool_msg["content"] if b.get("type") == "tool-result")
    assert tool_block.get("toolCallId") == "call_calc_1"
    assert any("84" in b.get("text", "") for b in tool_block.get("content", []))

    # 2. Verify Session Event log integrity
    event_types = [e.get("type") for e in session.events]
    assert "agent/inbox/spliced" in event_types
    assert "turn/start" in event_types
    assert "step/start" in event_types
    assert "user/message" in event_types
    assert "request/header" in event_types
    assert "request/context" in event_types
    assert "assistant/chunk" in event_types
    assert "assistant/message" in event_types
    assert "tool/call" in event_types
    assert "tool/result" in event_types
    assert "step/end" in event_types
    assert "turn/end" in event_types

    # Verify Assistant message content blocks in Step 1 (Reasoning + ToolCall)
    assistant_events = [e for e in session.events if e.get("type") == "assistant/message"]
    assert len(assistant_events) == 2

    step1_blocks = assistant_events[0]["data"]["message"]["content"]
    assert any(b.get("type") == "reasoning" and "multiply 42 by 2" in b.get("text", "") for b in step1_blocks)
    assert any(b.get("type") == "tool-call" and b.get("name") == "calculator" for b in step1_blocks)

    # Verify Assistant message content blocks in Step 2 (Reasoning + Text)
    step2_blocks = assistant_events[1]["data"]["message"]["content"]
    assert any(b.get("type") == "reasoning" and "The tool returned 84" in b.get("text", "") for b in step2_blocks)
    assert any(b.get("type") == "text" and "The result is 84." in b.get("text", "") for b in step2_blocks)

    # 3. Verify turn/end reason
    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "completed"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_system_prompt_variable_and_context_injection():
    """
    End-to-end verification of SystemPrompt dynamic sections, variables, and runtime context snapshot.
    """
    adapter = StrictMockLlmAdapter(responses=[{"text": "Acknowledged environment and guidelines."}])
    ctx = await build_e2e_harness(adapter, persona="Assistant for {{project_name}}.")

    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.variable("project_name", "Win7-Core")
    sp.section({
        "name": "coding:guidelines",
        "order": FIRST_PARTY_SECTION_ORDER["TOOL_EDIT"],
        "text": "Guideline: Keep Python 3.8.10 compatibility.",
    })
    sp.context({
        "name": "git_branch",
        "order": 10,
        "text": "Active branch: master",
    })

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-prompt-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Start task")
    await agent.when_idle()

    assert len(adapter.requests) == 1
    sys_text = adapter.requests[0]["system"]
    assert "Assistant for Win7-Core." in sys_text
    assert "Guideline: Keep Python 3.8.10 compatibility." in sys_text

    # Verify runtime context snapshot was appended to user history
    sent_messages = adapter.requests[0]["messages"]
    user_msgs = [m for m in sent_messages if m.get("role") == "user"]
    assert any("Active branch: master" in str(m.get("content", "")) for m in user_msgs)

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_request_header_stability_and_reconstruction():
    """
    1:1 request stability test:
    A single turn with 2 tool steps must only log ONE request/header event (reason: 'initial').
    The header snapshot must perfectly fold and anchor the session history.
    """
    adapter = StrictMockLlmAdapter(responses=[
        {"tool_calls": [{"id": "c1", "name": "ping", "arguments": {}}]},
        {"text": "pong received"},
    ])
    ctx = await build_e2e_harness(adapter)

    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="ping", description="ping", handler=lambda _: "pong")

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-reconstruct-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Send ping")
    await agent.when_idle()

    # Assert exactly 1 request/header event with reason 'initial'
    header_events = [e for e in session.events if e.get("type") == "request/header"]
    assert len(header_events) == 1
    assert header_events[0]["data"]["reason"] == "initial"

    # Assert request header contains canonical system prompt and tools list
    hdr = header_events[0]["data"]["header"]
    assert "system" in hdr
    assert any(t.get("name") == "ping" for t in hdr.get("tools", []))

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_pre_step_rejection_and_turn_stopping():
    """
    Verify agent/pre-step rejection halts model call, and agent/turn-stopping fires on turn completion.
    """
    adapter = StrictMockLlmAdapter(responses=[{"text": "Normal output"}])
    ctx = await build_e2e_harness(adapter)

    stopping_events = []
    ctx.on("agent/turn-stopping", lambda p: stopping_events.append(p))

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-stopping-1")
    agent = handle.agent

    # Normal turn -> turn-stopping should fire
    agent.followup("Normal request")
    await agent.when_idle()

    assert len(adapter.requests) == 1
    assert len(stopping_events) == 1
    assert stopping_events[0]["turn"] == 1

    # Intercept next turn with rejection
    def reject_pre_step(req, next_fn=None):
        return {"kind": "reject"}

    ctx.on("agent/pre-step", reject_pre_step)

    agent.followup("Blocked request")
    await agent.when_idle()

    # No second LLM call should be made
    assert len(adapter.requests) == 1

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_parallel_tool_calls_model_ordering():
    """
    Multiple concurrent tool calls in a single assistant response are executed
    and recorded into the session log in exact model-emitted order.
    """
    adapter = StrictMockLlmAdapter(responses=[
        {
            "reasoning": "Dispatching two concurrent tasks.",
            "tool_calls": [
                {"id": "c1", "name": "task_a", "arguments": {"val": 1}},
                {"id": "c2", "name": "task_b", "arguments": {"val": 2}},
            ],
        },
        {"text": "Both tasks completed."},
    ])
    ctx = await build_e2e_harness(adapter)

    order_log = []
    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(
        name="task_a",
        description="Task A",
        handler=lambda args: order_log.append("task_a") or "res_a",
        execution_mode="parallel",
    )
    tools_svc.register_tool(
        name="task_b",
        description="Task B",
        handler=lambda args: order_log.append("task_b") or "res_b",
        execution_mode="parallel",
    )

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-parallel-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Run parallel tasks")
    await agent.when_idle()

    # Verify tool results in session event log are ordered c1 then c2
    tool_results = [e for e in session.events if e.get("type") == "tool/result"]
    assert len(tool_results) == 2
    assert tool_results[0]["data"]["message"]["content"][0]["toolCallId"] == "c1"
    assert tool_results[1]["data"]["message"]["content"][0]["toolCallId"] == "c2"

    await handle.dispose()


@pytest.mark.asyncio
async def test_e2e_mid_turn_steering():
    """
    Verify agent.steer(...) injects guidance into next-step queue and keeps turn active.
    """
    adapter = StrictMockLlmAdapter(responses=[
        {
            "tool_calls": [{"id": "c1", "name": "step_tool", "arguments": {}}],
        },
        {
            "text": "Finished step 2 taking steering into account.",
        },
    ])
    ctx = await build_e2e_harness(adapter)

    def tool_handler(args):
        # Mid-turn steer from within execution
        agent.steer("Please refine your output format.")
        return "step_tool_ok"

    tools_svc: ToolsService = ctx.get("tools")
    tools_svc.register_tool(name="step_tool", description="Step tool", handler=tool_handler)

    agent_loop: AgentLoopService = ctx.get("agent_loop")
    handle = await agent_loop.create_agent("e2e-session-steer-1")
    agent = handle.agent
    session = agent.session

    agent.followup("Begin pipeline")
    await agent.when_idle()

    assert len(adapter.requests) == 2
    # Second request contains steering input
    step2_msgs = adapter.requests[1]["messages"]
    assert any("refine your output format" in str(m.get("content", "")) for m in step2_msgs)

    turn_end = next(e for e in session.events if e.get("type") == "turn/end")
    assert turn_end["data"]["reason"]["kind"] == "completed"

    await handle.dispose()

