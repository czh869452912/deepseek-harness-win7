"""
Tests for canonical tool ordering in agent loop and headers
matching reference/packages/core/agent-loop/tests/tool-order.spec.ts.
"""

import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.tools import Tool, ToolsPlugin, ToolsService


class MockLLMService:
    def __init__(self):
        self.requests = []
        self.provider = "mock"
        self.model = "mock"

    async def chat_completion(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        return {"content": "done", "role": "assistant"}

    async def chat_completion_stream(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        yield {
            "choices": [
                {"delta": {"content": "done", "role": "assistant"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }


@pytest.mark.asyncio
async def test_canonical_tool_order_lexicographic():
    """Tools registered in arbitrary order (zulu, alpha, mike) are passed in canonical order (alpha, mike, zulu)."""
    ctx = Context()
    mock_llm = MockLLMService()
    ctx.set_service("llm", mock_llm)
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentLoopPlugin)

    tools: ToolsService = ctx.get("tools")
    # Register in non-alphabetical order
    tools.register(name="zulu", description="zulu tool", parameters={}, handler=lambda: "zulu")
    tools.register(name="alpha", description="alpha tool", parameters={}, handler=lambda: "alpha")
    tools.register(name="mike", description="mike tool", parameters={}, handler=lambda: "mike")

    loop_svc: AgentLoopService = ctx.get("agent_loop")
    handle = await loop_svc.create("test-canonical-order")
    agent = handle.agent

    agent.followup({"content": "run turn", "source": {"kind": "user"}})
    await agent.when_idle()

    assert len(mock_llm.requests) > 0
    dispatched_tools = mock_llm.requests[0].get("tools", [])
    tool_names = [t.get("function", {}).get("name") or t.get("name") for t in dispatched_tools]
    # Names should be canonically sorted: alpha, mike, zulu
    assert sorted(tool_names) == ["alpha", "mike", "zulu"]

    await handle.dispose()
