import pytest
from dsh.compaction.engine import (
    BasicCompactionEngine,
    select_compactable_range,
)
from dsh.compaction.pruner import ToolResultPruner
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.llm.token_meter import TokenMeter


class MockLlmService:
    def __init__(self):
        self.model = "deepseek-chat"

    def chat_completion(self, messages, tools=None):
        return {
            "role": "assistant",
            "content": "This is a condensed summary of the previous conversation steps.",
        }


def test_select_compactable_range():
    session = Session(session_id="select-range-test")
    # seq 0: user msg
    session.append_user_message("User 1")
    # seq 1: assistant msg
    session.append_assistant_message({"role": "assistant", "content": "Assistant 1"})
    # seq 2: user msg
    session.append_user_message("User 2")
    # seq 3: assistant msg
    session.append_assistant_message({"role": "assistant", "content": "Assistant 2"})

    measurement = {
        "nodes": [
            {"seq": 0, "tokens": 100},
            {"seq": 1, "tokens": 100},
            {"seq": 2, "tokens": 100},
            {"seq": 3, "tokens": 100},
        ]
    }

    # If retain_tokens is 150, we want to retain the tail (seq 3 + seq 2 = 200 tokens >= 150)
    # The range to compact should be [0, 1]
    rng = select_compactable_range(session, measurement, retain_tokens=150)
    assert rng is not None
    assert rng["start"] == 0
    assert rng["end"] == 1


@pytest.mark.asyncio
async def test_compact_surface_region():
    ctx = Context()
    meter = TokenMeter(ctx)
    ctx.set_service("token_meter", meter)

    llm = MockLlmService()
    ctx.set_service("llm", llm)

    engine = BasicCompactionEngine(ctx=ctx)
    session = Session(session_id="compact-region-test", ctx=ctx)

    session.append_user_message("Step 1: start project")
    session.append_assistant_message({"role": "assistant", "content": "Started"})
    session.append_user_message("Step 2: build code")
    session.append_assistant_message({"role": "assistant", "content": "Built"})

    assert session.surface.nodes == [0, 1, 2, 3]

    # Compact range [0, 1]
    result = await engine.compact_surface_region(session, start=0, end=1)
    assert result["startSeq"] is not None
    assert result["summarySeq"] is not None
    assert result["endSeq"] is not None
    assert "condensed summary" in result["summary"]

    # Surface should now contain the replacement user message in place of [0, 1]
    assert session.surface.replace_generation == 1
    # Nodes should be [replacement_seq, 2, 3]
    nodes = session.surface.nodes
    assert len(nodes) == 3
    assert nodes[1] == 2
    assert nodes[2] == 3

    # Derived messages should start with the summary
    messages = session.derive_messages()
    assert len(messages) == 3
    assert "<summary>" in str(messages[0]["content"])


@pytest.mark.asyncio
async def test_automatic_pressure_compaction():
    ctx = Context()
    meter = TokenMeter(ctx)
    ctx.set_service("token_meter", meter)

    pruner = ToolResultPruner(ctx=ctx)
    ctx.set_service("tool_result_pruner", pruner)

    llm = MockLlmService()
    ctx.set_service("llm", llm)

    store = SessionStore(ctx=ctx)
    ctx.set_service("sessions", store)
    session = store.create("pressure-session")

    # Set very low threshold (e.g. 50 tokens) to trigger compaction
    engine = BasicCompactionEngine(threshold_tokens=50, retain_tokens=20, auto=False, ctx=ctx)
    ctx.set_service("compaction", engine)

    session.append_user_message("Prompt 1 with some text to consume tokens")
    session.append_assistant_message({"role": "assistant", "content": "Response 1 with text"})
    session.append_user_message("Prompt 2 with some text to consume tokens")
    session.append_assistant_message({"role": "assistant", "content": "Response 2 with text"})

    # Check compaction
    comp_result = await engine.compact_if_needed(trigger="pressure")
    assert comp_result is not None
    assert session.surface.replace_generation >= 1
