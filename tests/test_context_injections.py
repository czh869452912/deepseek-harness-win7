import pytest
from dsh.cordis.context import Context
from dsh.context.file_reference_local import FileReferenceLocalPlugin
from dsh.context.time_context import TimeContextPlugin
from dsh.core.agent import AgentPlugin


@pytest.mark.asyncio
async def test_file_reference_local_injection(tmp_path):
    ctx = Context()
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(FileReferenceLocalPlugin)

    # Create a test file
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    # Simulate agent/pre-step event with @sample.py mention
    payload = {
        "messages": [
            {"role": "user", "content": "Please check @sample.py and fix it."}
        ]
    }

    await ctx.waterfall("agent/pre-step", payload, lambda: payload)
    user_msg = payload["messages"][0]["content"]

    assert user_msg == "Please check @sample.py and fix it."
    assert "def hello():" not in user_msg
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_time_context_injection():
    ctx = Context()
    await ctx.plugin(TimeContextPlugin)

    payload = {
        "session_id": "test-session",
        "messages": [
            {"role": "user", "content": "What is the current time?"}
        ]
    }

    await ctx.waterfall("agent/pre-step", payload, lambda: payload)
    user_msg = payload["messages"][0]["content"]

    assert "Time sampled while preparing turn" in user_msg
    assert "Elapsed since the preceding" in user_msg
