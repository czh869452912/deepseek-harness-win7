import io
import sys
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService, ToolExecutionInput, ToolExecutionResult
from dsh.extensions.cli_visualizer import CliVisualizerPlugin


@pytest.mark.asyncio
async def test_cli_visualizer_plugin_events():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    await ctx.plugin(CliVisualizerPlugin, config={"verbose": True})

    captured_output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured_output

    try:
        ctx.emit("turn/start", "Test User Prompt")
        ctx.emit("step/start", 1)

        payload = {"name": "test_tool", "arguments": {"path": "test.txt"}}
        await ctx.waterfall("tools/pre-execute", payload, lambda *_args: payload)

        execution = ToolExecutionInput("call-1", "test_tool", {}, signal=None)
        result = ToolExecutionResult([{ "type": "text", "text": "Success Content"}])
        await ctx.waterfall("tools/post-execute", execution, result, lambda *_args: {"kind": "accept"})

        ctx.emit("turn/end", "Test Final Response")
    finally:
        sys.stdout = old_stdout

    output = captured_output.getvalue()
    assert "[Turn Started]" in output
    assert "[Step 1]" in output
    assert "[Executing Tool] test_tool" in output
    assert "[Tool Done] test_tool" in output
    assert "[Turn Complete]" in output
