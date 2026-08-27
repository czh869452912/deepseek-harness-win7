import io
import sys
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.extensions.cli_visualizer import CliVisualizerPlugin


@pytest.mark.asyncio
async def test_cli_visualizer_plugin_events():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    await ctx.registry.plugin(CliVisualizerPlugin, config={"verbose": True})

    captured_output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured_output

    try:
        ctx.emit("turn/start", "Test User Prompt")
        ctx.emit("step/start", 1)

        payload = {"name": "test_tool", "arguments": {"path": "test.txt"}}
        await ctx.waterfall("tools/pre-execute", payload, lambda *_args: payload)

        res_payload = {"name": "test_tool", "result": "Success Content", "error": None}
        await ctx.waterfall("tools/post-execute", res_payload, lambda *_args: res_payload)

        ctx.emit("turn/end", "Test Final Response")
    finally:
        sys.stdout = old_stdout

    output = captured_output.getvalue()
    assert "[Turn Started]" in output
    assert "[Step 1]" in output
    assert "[Executing Tool] test_tool" in output
    assert "[Tool Done] test_tool" in output
    assert "[Turn Complete]" in output
