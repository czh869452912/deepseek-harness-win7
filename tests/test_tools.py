import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin
from dsh.shell.tool_pwsh_persistent import ToolPwshPersistentPlugin


@pytest.fixture
def ctx_with_tools():
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    return ctx


def test_str_replace_editor_plugin(ctx_with_tools):
    ctx = ctx_with_tools
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx.plugin(FsLocalPlugin, config={"cwd": tmpdir})
        plugin = ctx.plugin(StrReplaceEditorPlugin)

        test_file = os.path.join(tmpdir, "test.txt")

        # 1. Create file
        res = plugin.handle_editor("create", path=test_file, file_text="Hello World\nLine 2\nLine 3", ctx=ctx)
        assert "New file created successfully at:" in res

        # 2. View file
        view_res = plugin.handle_editor("view", path=test_file, ctx=ctx)
        assert "Hello World" in view_res
        assert "Line 2" in view_res

        # 3. String replace
        rep_res = plugin.handle_editor("str_replace", path=test_file, old_str="Line 2", new_str="Line Two", ctx=ctx)
        assert "The file" in rep_res and "has been edited successfully" in rep_res

        view_res2 = plugin.handle_editor("view", path=test_file, ctx=ctx)
        assert "Line Two" in view_res2



def test_pwsh_persistent_plugin(ctx_with_tools):
    ctx = ctx_with_tools
    plugin = ctx.plugin(ToolPwshPersistentPlugin)

    res = plugin.handle_pwsh("echo 'Hello Win7 Harness'", ctx=ctx)
    assert "Hello Win7 Harness" in res


def test_tool_registration_disposer(ctx_with_tools):
    ctx = ctx_with_tools
    tools = ctx.get("tools")
    
    disposer = tools.register_legacy({
        "name": "custom_tool",
        "description": "Custom tool description",
        "parameters": {"type": "object", "properties": {}},
        "handler": lambda: "ok",
    })
    assert callable(disposer)
    assert tools.get_tool("custom_tool") is not None

    # Call disposer
    disposer()
    assert tools.get_tool("custom_tool") is None
