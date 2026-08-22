import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin, TRUNCATED_MESSAGE


@pytest.fixture
def editor_env():
    tmpdir = tempfile.mkdtemp()
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.plugin(FsLocalPlugin, config={"cwd": tmpdir})
    ctx.plugin(StrReplaceEditorPlugin, config={"maxOutputChars": 16000})
    yield ctx, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)



@pytest.mark.asyncio
async def test_str_replace_create_and_edit(editor_env):
    ctx, tmpdir = editor_env
    tools = ctx.get("tools")
    file_path = os.path.join(tmpdir, "test.txt")

    # Create file
    res = await tools.execute_tool("str_replace_editor", {"command": "create", "path": file_path, "file_text": "line1\nline2\nline3"})
    assert "New file created successfully at:" in res

    # Replace line2
    res2 = await tools.execute_tool("str_replace_editor", {"command": "str_replace", "path": file_path, "old_str": "line2", "new_str": "modified_line2"})
    assert "The file" in res2 and "has been edited successfully" in res2

    # View content
    res_view = await tools.execute_tool("str_replace_editor", {"command": "view", "path": file_path})
    assert "modified_line2" in res_view

    # Insert after line 2
    res_insert = await tools.execute_tool("str_replace_editor", {"command": "insert", "path": file_path, "insert_line": 2, "new_str": "inserted_line"})
    assert "has been edited successfully" in res_insert

    # View again
    res_view2 = await tools.execute_tool("str_replace_editor", {"command": "view", "path": file_path})
    assert "inserted_line" in res_view2


@pytest.mark.asyncio
async def test_str_replace_multi_occurrence_lines(editor_env):
    ctx, tmpdir = editor_env
    tools = ctx.get("tools")
    file_path = os.path.join(tmpdir, "multi.txt")

    # Create file with duplicate lines
    content = "apple\nbanana\napple\norange\napple\n"
    await tools.execute_tool("str_replace_editor", {"command": "create", "path": file_path, "file_text": content})

    # Attempt to replace non-unique "apple"
    res = await tools.execute_tool("str_replace_editor", {"command": "str_replace", "path": file_path, "old_str": "apple", "new_str": "pear"})
    assert "Multiple occurrences of old_str `apple` in lines [1, 3, 5]" in res


@pytest.mark.asyncio
async def test_str_replace_view_directory_2_levels(editor_env):
    ctx, tmpdir = editor_env
    tools = ctx.get("tools")

    # Create nested directories & files
    os.makedirs(os.path.join(tmpdir, "subdir", "nested"), exist_ok=True)
    with open(os.path.join(tmpdir, "subdir", "file1.txt"), "w") as f:
        f.write("hello")
    with open(os.path.join(tmpdir, "root_file.txt"), "w") as f:
        f.write("root")

    res = await tools.execute_tool("str_replace_editor", {"command": "view", "path": tmpdir})
    assert "Here're the files and directories up to 2 levels deep in" in res
    assert "root_file.txt" in res
    assert "subdir" in res
    assert "file1.txt" in res


@pytest.mark.asyncio
async def test_str_replace_bool_insert_line_validation(editor_env):
    ctx, tmpdir = editor_env
    tools = ctx.get("tools")
    file_path = os.path.join(tmpdir, "bool_test.txt")
    await tools.execute_tool("str_replace_editor", {"command": "create", "path": file_path, "file_text": "a\nb\n"})

    res = await tools.execute_tool("str_replace_editor", {
        "command": "insert",
        "path": file_path,
        "insert_line": True,
        "new_str": "invalid",
    })
    assert "Error: Invalid `insert_line` parameter" in res


