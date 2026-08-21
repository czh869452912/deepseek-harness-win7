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


@pytest.mark.asyncio
async def test_1to1_tools_schema_and_descriptions():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("web", WebService())
    ctx.plugin(SessionProjectionsPlugin)

    ctx.plugin(StrReplaceEditorPlugin)
    ctx.plugin(ToolFsSearchPlugin)
    ctx.plugin(ToolTodoPlugin)
    ctx.plugin(ToolWebPlugin)

    # 1. str_replace_editor tool schema
    tool_editor = tools.get_tool("str_replace_editor")
    assert tool_editor is not None
    commands = tool_editor.parameters["properties"]["command"]["enum"]
    assert commands == ["view", "create", "str_replace", "insert"]
    assert "undo_edit" not in commands

    # 2. grep parameters schema
    tool_grep = tools.get_tool("grep")
    assert tool_grep is not None
    assert set(tool_grep.parameters["properties"].keys()) == {"pattern", "path", "include"}

    # 3. glob parameters schema
    tool_glob = tools.get_tool("glob")
    assert tool_glob is not None
    assert set(tool_glob.parameters["properties"].keys()) == {"pattern", "path"}

    # 4. todo_write parameters schema
    tool_todo = tools.get_tool("todo_write")
    assert tool_todo is not None
    assert "todos" in tool_todo.parameters["properties"]

    # 5. web_search parameters schema
    tool_search = tools.get_tool("web_search")
    assert tool_search is not None
    assert "queries" in tool_search.parameters["properties"]
