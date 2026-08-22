import os
import pytest
from dsh.cordis.context import Context
from dsh.context.file_reference_local import FileReferenceLocalPlugin
from dsh.context.time_context import TimeContextPlugin
from dsh.fs.fs_local import FsLocalPlugin


@pytest.mark.asyncio
async def test_file_reference_local_injection(tmp_path):
    ctx = Context()
    fs_plugin = FsLocalPlugin({"cwd": str(tmp_path)})
    ctx.plugin(fs_plugin)
    ctx.plugin(FileReferenceLocalPlugin)

    # Create a test file
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    # Simulate agent/pre-step event with @sample.py mention
    payload = {
        "messages": [
            {"role": "user", "content": "Please check @sample.py and fix it."}
        ]
    }

    result = await ctx.waterfall("agent/pre-step", payload)
    user_msg = payload["messages"][0]["content"]

    assert "@sample.py content" in user_msg
    assert "def hello():" in user_msg


@pytest.mark.asyncio
async def test_time_context_injection():
    ctx = Context()
    ctx.plugin(TimeContextPlugin)

    payload = {
        "session_id": "test-session",
        "messages": [
            {"role": "user", "content": "What is the current time?"}
        ]
    }

    await ctx.waterfall("agent/pre-step", payload)
    user_msg = payload["messages"][0]["content"]

    assert "Time sampled while preparing turn" in user_msg
    assert "Elapsed since the preceding" in user_msg
