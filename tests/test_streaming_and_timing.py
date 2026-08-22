import json
import pytest
from dsh.cordis.context import Context
from dsh.llm.llm_service import LLMService
from dsh.core.session import Session, SessionStore
from dsh.core.agent_loop import AgentLoopService


def test_session_append_with_timing_and_usage():
    ctx = Context()
    session = Session.create("test-session", ctx=ctx)

    timing = {
        "stepStartTime": 1000.0,
        "firstTokenTime": 1250.0,
        "completedTime": 2500.0,
        "ttftMs": 250.0,
        "decodingMs": 1250.0,
        "durationMs": 1500.0,
    }
    usage = {
        "inputTokens": 100,
        "outputTokens": 50,
        "cacheReadTokens": 20,
    }

    event = session.append_assistant_message(
        {"role": "assistant", "content": "Hello world", "reasoning_content": "Thinking..."},
        turn=1,
        step=1,
        timing=timing,
        usage=usage,
    )

    assert event["type"] == "assistant/message"
    assert event["data"]["turn"] == 1
    assert event["data"]["timing"]["ttftMs"] == 250.0
    assert event["data"]["usage"]["inputTokens"] == 100
    assert event["data"]["message"]["reasoning_content"] == "Thinking..."


@pytest.mark.asyncio
async def test_agent_loop_with_stream_mock():
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    session = sessions.create("stream-session")

    class MockStreamLLM:
        def __init__(self):
            self.call_count = 0

        def chat_completion_stream(self, messages, tools=None, model=None, temperature=0.0):
            self.call_count += 1
            yield ("chunk", {
                "delta_type": "reasoning",
                "delta": "Thinking step 1",
                "reasoning": "Thinking step 1",
                "content": "",
            })
            yield ("chunk", {
                "delta_type": "text",
                "delta": "Hello from stream",
                "reasoning": "Thinking step 1",
                "content": "Hello from stream",
            })
            yield ("finish", {
                "message": {
                    "role": "assistant",
                    "content": "Hello from stream",
                    "reasoning_content": "Thinking step 1",
                },
                "timing": {
                    "stepStartTime": 1000.0,
                    "firstTokenTime": 1200.0,
                    "completedTime": 1800.0,
                    "ttftMs": 200.0,
                    "decodingMs": 600.0,
                    "durationMs": 800.0,
                },
                "usage": {"inputTokens": 50, "outputTokens": 20}
            })

        def resolve_model(self, m=None): return "mock-model"
        def resolve_base_url(self): return "https://mock.api"

    mock_llm = MockStreamLLM()
    ctx.set_service("llm", mock_llm)

    chunks_received = []
    ctx.on("assistant/chunk", lambda data: chunks_received.append(data))

    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)

    handle = await agent_loop.create_agent("stream-session")
    agent = handle.agent
    agent.followup("Stream test input")
    await agent.when_idle()

    # Verify chunks received
    assert len(chunks_received) == 2
    assert chunks_received[0]["data"]["delta_type"] == "reasoning"
    assert chunks_received[1]["data"]["delta_type"] == "text"

    # Verify final session event has timing and usage
    asst_events = [e for e in session.events if e["type"] == "assistant/message"]
    assert len(asst_events) == 1
    assert asst_events[0]["data"]["timing"]["ttftMs"] == 200.0

    content = asst_events[0]["data"]["message"]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    assert text == "Hello from stream"
