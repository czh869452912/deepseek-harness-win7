import io
import sys
import pytest
from dsh.cordis.context import Context
from dsh.plugins.cli_visualizer import CliVisualizerPlugin
from dsh.services.tools import ToolsService


@pytest.mark.asyncio
async def test_cli_visualizer_plugin_events():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.plugin(CliVisualizerPlugin, config={"verbose": True})

    # Capture stdout
    captured_output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured_output

    try:
        ctx.emit("turn/start", "Test User Prompt")
        ctx.emit("step/start", 1)

        payload = {"name": "test_tool", "arguments": {"path": "test.txt"}}
        await ctx.waterfall("tools/pre-execute", payload)

        res_payload = {"name": "test_tool", "result": "Success Content", "error": None}
        await ctx.waterfall("tools/post-execute", res_payload)

        ctx.emit("turn/end", "Test Final Response")
    finally:
        sys.stdout = old_stdout

    output = captured_output.getvalue()
    assert "[Turn Started]" in output
    assert "[Step 1]" in output
    assert "[Executing Tool] test_tool" in output
    assert "[Tool Done] test_tool" in output
    assert "[Turn Complete]" in output
