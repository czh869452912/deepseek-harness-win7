import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions, AgentPlugin, AgentRegistry
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import Session, SessionPlugin
from dsh.core.tools import ToolsService


class MockLlmDriver:
    def __init__(self):
        self.model = "deepseek-chat"
        self.call_count = 0

    def chat_completion(self, messages, tools=None):
        self.call_count += 1
        return {
            "role": "assistant",
            "content": f"Response {self.call_count} for task.",
        }


def test_agent_initiator_scope():
    registry = AgentRegistry()
    session = Session(session_id="initiator-test")
    agent = Agent(session=session)

    assert registry.current_initiator() is None

    def worker():
        assert registry.current_initiator() == agent
        assert registry.require_initiator() == agent
        return "ok"

    res = registry.with_initiator(agent, worker)
    assert res == "ok"
    assert registry.current_initiator() is None


@pytest.mark.asyncio
async def test_agent_create_followup_and_when_idle():
    ctx = Context()
    ctx.set_service("llm", MockLlmDriver())
    ctx.plugin(SessionPlugin)
    ctx.plugin(AgentPlugin)
    ctx.plugin(AgentLoopPlugin)

    registry: AgentRegistry = ctx.get("agents")
    handle = await registry.create(session_id="scheduled-agent-1")
    agent = handle.agent

    status_transitions = []
    ctx.on("agent/status", lambda p: status_transitions.append(p["status"]))

    assert agent.status == "idle"

    # Send prompt via followup
    agent.followup("First task")
    await agent.when_idle()

    assert agent.status == "idle"
    assert "running" in status_transitions

    # Check session log has events
    events = agent.session.events
    types = [e["type"] for e in events]
    assert "turn/start" in types
    assert "user/message" in types
    assert "assistant/message" in types
    assert "turn/end" in types

    await handle.dispose()


@pytest.mark.asyncio
async def test_agent_cancel():
    ctx = Context()
    ctx.set_service("llm", MockLlmDriver())
    ctx.plugin(SessionPlugin)
    ctx.plugin(AgentPlugin)
    ctx.plugin(AgentLoopPlugin)

    registry: AgentRegistry = ctx.get("agents")
    handle = await registry.create(session_id="cancel-agent-1")
    agent = handle.agent

    agent.followup("Task to be cancelled")
    agent.cancel(cause={"kind": "user"}, keep_inbox=False)

    await agent.when_idle()
    assert agent.status == "idle"
    assert agent.inbox.is_empty()

    await handle.dispose()
