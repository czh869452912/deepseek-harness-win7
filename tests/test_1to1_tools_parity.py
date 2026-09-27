import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin
from dsh.todo.tool_todo import ToolTodoPlugin
from dsh.web.tool_web import ToolWebPlugin
from dsh.web.web_service import WebService
from dsh.session.projections import SessionProjectionsPlugin


class PromptService:
    def section(self, *args, **kwargs):
        return lambda: None


@pytest.mark.asyncio
async def test_1to1_tools_schema_and_descriptions():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("web", WebService())
    ctx.set_service("systemPrompt", PromptService())
    ctx.set_service("subprocess", object())
    fibers = [
        ctx.registry.plugin(FsLocalPlugin, parent_ctx=ctx),
        ctx.registry.plugin(StrReplaceEditorPlugin, parent_ctx=ctx),
            ctx.registry.plugin(
                ToolFsSearchPlugin,
                config={"sampleOverCapGlobResults": False},
                parent_ctx=ctx,
            ),
        ctx.registry.plugin(
            ToolTodoPlugin,
            config={"allowParallelInProgress": True},
            parent_ctx=ctx,
        ),
        ctx.registry.plugin(ToolWebPlugin, parent_ctx=ctx),
    ]
    try:
        for fiber in fibers:
            await fiber

        # 1. str_replace_editor tool schema
        tool_editor = tools.get_tool("str_replace_editor", fibers[1].ctx)
        assert tool_editor is not None
        commands = tool_editor.parameters["properties"]["command"]["enum"]
        assert commands == ["view", "create", "str_replace", "insert"]
        assert "undo_edit" not in commands

        # 2. grep parameters schema
        tool_grep = tools.get_tool("grep", fibers[2].ctx)
        assert tool_grep is not None
        assert set(tool_grep.parameters["properties"].keys()) == {"pattern", "path", "include"}

        # 3. glob parameters schema
        tool_glob = tools.get_tool("glob", fibers[2].ctx)
        assert tool_glob is not None
        assert set(tool_glob.parameters["properties"].keys()) == {"pattern", "path"}

        # 4. todo_write parameters schema
        tool_todo = tools.get_tool("todo_write", fibers[3].ctx)
        assert tool_todo is not None
        assert "todos" in tool_todo.parameters["properties"]

        # 5. web_search parameters schema
        tool_search = tools.get_tool("web_search", fibers[4].ctx)
        assert tool_search is not None
        assert "queries" in tool_search.parameters["properties"]
    finally:
        for fiber in reversed(fibers):
            await fiber.dispose()
