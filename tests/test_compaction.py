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

    async def stream(self, request):
        assert request['purpose'] == 'compaction'
        assert request['messages'][0]['content']
        yield {'type': 'text-delta', 'index': 0, 'text': 'condensed summary'}
        yield {'type': 'finish', 'reason': {'kind': 'stop'}}


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
    assert select_compactable_range(session, measurement, retain_tokens=1000) is None


@pytest.mark.asyncio
async def test_pressure_compaction_ignores_non_surface_events_and_preserves_short_history():
    ctx = Context()
    engine = BasicCompactionEngine(ctx=ctx)
    ctx.set_service('token_meter', TokenMeter(ctx))
    session = Session(session_id='short', ctx=ctx)
    session.append('turn/start', dict(turn=1))
    session.append_user_message('keep this')
    before = list(session.events)
    result = await engine.compact_if_needed(session=session)
    assert result == dict(status='no_compaction_needed')
    assert session.events == before and session.surface.replace_generation == 0
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_compact_surface_region():
    ctx = Context()
    meter = TokenMeter(ctx)
    ctx.set_service("token_meter", meter)

    llm = MockLlmService()
    ctx.set_service("llm", llm)

    engine = BasicCompactionEngine(config={"summarizationProvider": "test", "summarizationModel": "test"}, ctx=ctx)
    session = Session(session_id="compact-region-test", ctx=ctx)

    session.append_user_message("Step 1: start project" * 100)
    session.append("step/start", dict(turn=1, step=1))
    session.append_assistant_message({"role": "assistant", "content": "Started"})
    session.append("step/end", dict(turn=1, step=1))
    session.append_user_message("Step 2: build code")
    session.append("step/start", dict(turn=1, step=2))
    session.append_assistant_message({"role": "assistant", "content": "Built"}, step=2)
    session.append("step/end", dict(turn=1, step=2))

    assert session.surface.nodes == [0, 2, 4, 6]

    # Compact the first user/assistant pair, whose surface seqs are [0, 2].
    result = await engine.compact_surface_region(session, start=0, end=2, manual=True)
    assert result["startSeq"] is not None
    assert result["summarySeq"] is not None
    assert result["endSeq"] is not None
    assert "condensed summary" in str(result["summary"])

    # Replace the first pair while preserving the second pair.
    assert session.surface.replace_generation == 1
    # Nodes should be [replacement_seq, 4, 6].
    nodes = session.surface.nodes
    assert len(nodes) == 3
    assert nodes[1] == 4
    assert nodes[2] == 6

    # Derived messages should start with the summary
    messages = session.derive_messages()
    assert len(messages) == 3
    assert "<compacted-summary>" in str(messages[0]["content"])


@pytest.mark.asyncio
async def test_automatic_pressure_compaction():
    ctx = Context()
    meter = TokenMeter(ctx)
    ctx.set_service("token_meter", meter)

    pruner = ToolResultPruner(ctx=ctx)

    llm = MockLlmService()
    ctx.set_service("llm", llm)

    store = SessionStore(ctx=ctx)
    ctx.set_service("sessions", store)
    session = store.create("pressure-session")

    # Set very low threshold (e.g. 50 tokens) to trigger compaction
    engine = BasicCompactionEngine(config={"summarizationProvider": "test", "summarizationModel": "test"}, threshold_tokens=50, retain_tokens=20, auto=False, ctx=ctx)

    session.append("turn/start", {"turn": 1})
    session.append_user_message("Prompt 1 with some text to consume tokens" * 100)
    session.append("step/start", dict(turn=1, step=1))
    session.append_assistant_message({"role": "assistant", "content": "Response 1 with text"})
    session.append("step/end", dict(turn=1, step=1))
    session.append_user_message("Prompt 2 with some text to consume tokens")
    session.append("step/start", dict(turn=1, step=2))
    session.append_assistant_message({"role": "assistant", "content": "Response 2 with text"}, step=2)
    session.append("step/end", dict(turn=1, step=2))

    # Check compaction
    comp_result = await engine.compact_if_needed(trigger="pressure")
    assert comp_result is not None
    assert session.surface.replace_generation >= 1
