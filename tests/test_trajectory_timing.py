import pytest
import time
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.core.agent_loop import AgentLoopService
from dsh.core.tools import ToolsService


def test_trajectory_tool_timing_and_metrics():
    ctx = Context()
    session = Session.create("test-trajectory-session", ctx=ctx)

    # 1. Tool execution timing event
    timing = {
        "startedAt": 1000.0,
        "durationMs": 420.5,
    }
    tool_event = session.append_tool_result(
        tool_call_id="call-123",
        name="tool_str_replace_editor",
        result="File edited successfully",
        turn=1,
        step=1,
        timing=timing,
    )

    assert tool_event["type"] == "tool/result"
    assert tool_event["data"]["turn"] == 1
    assert tool_event["data"]["step"] == 1
    assert tool_event["data"]["timing"]["durationMs"] == 420.5
    assert tool_event["data"]["timing"]["startedAt"] == 1000.0


@pytest.mark.asyncio
async def test_agent_loop_tool_execution_timing():
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    session = sessions.create("test-loop-timing")

    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    def dummy_calc(val: int = 0):
        return f"result: {val * 2}"

    tools.register(
        name="dummy_calc",
        description="Calculate stuff",
        parameters={"type": "object", "properties": {"val": {"type": "number"}}},
        handler=dummy_calc,
    )

    class MockToolLLM:
        def __init__(self):
            self.calls = 0

        def chat_completion_stream(self, messages, tools=None, model=None, temperature=0.0):
            self.calls += 1
            if self.calls == 1:
                yield ("finish", {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-calc-1",
                            "type": "function",
                            "function": {"name": "dummy_calc", "arguments": '{"val": 21}'}
                        }]
                    },
                    "timing": {
                        "stepStartTime": 1000.0,
                        "firstTokenTime": 1100.0,
                        "completedTime": 1300.0,
                        "ttftMs": 100.0,
                        "decodingMs": 200.0,
                        "durationMs": 300.0,
                    },
                    "usage": {"inputTokens": 10, "outputTokens": 5}
                })
            else:
                yield ("finish", {
                    "message": {
                        "role": "assistant",
                        "content": "The result is 42",
                    },
                    "timing": {
                        "stepStartTime": 1400.0,
                        "firstTokenTime": 1450.0,
                        "completedTime": 1600.0,
                        "ttftMs": 50.0,
                        "decodingMs": 150.0,
                        "durationMs": 200.0,
                    },
                    "usage": {"inputTokens": 20, "outputTokens": 10}
                })

        def resolve_model(self, m=None): return "mock"
        def resolve_base_url(self): return "https://mock"

    ctx.set_service("llm", MockToolLLM())

    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)

    handle = await agent_loop.create_agent("test-loop-timing")
    agent = handle.agent
    agent.followup("Calculate 21 * 2")
    await agent.when_idle()

    # Check tool call and result events in session
    tool_call_events = [e for e in session.events if e["type"] == "tool/call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]["data"]["name"] == "dummy_calc"

    tool_events = [e for e in session.events if e["type"] == "tool/result"]
    assert len(tool_events) == 1
    tool_data = tool_events[0]["data"]
    assert "message" in tool_data or "timing" in tool_data
