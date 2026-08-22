import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.fs_local import FsLocalPlugin, FsService, FsTarget, FsError
from dsh.fs.tool_fs import ToolFsPlugin, format_read_output, format_write_output, format_edit_output
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin


@pytest.fixture
def fs_env():
    tmpdir = tempfile.mkdtemp(prefix="dsh_fs_test_")
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.plugin(FsLocalPlugin, config={"cwd": tmpdir})
    ctx.plugin(ToolFsPlugin)
    ctx.plugin(StrReplaceEditorPlugin)
    ctx.plugin(ToolFsSearchPlugin)
    yield ctx, tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_fs_local_service_parity(fs_env):
    ctx, tmpdir = fs_env
    fs: FsService = ctx.get("fs")
    assert fs is not None

    # Test resolve & target
    file_path = os.path.join(tmpdir, "test_file.txt")
    target = await fs.resolve(file_path)
    assert isinstance(target, FsTarget)
    assert target.targetKey == os.path.realpath(file_path)
    assert target.displayPath == os.path.realpath(file_path)

    # Test writeText & stat
    write_outcome = await fs.writeText(target, "line1\nline2\nline3\n")
    assert write_outcome.operation == "create"
    assert write_outcome.version is not None

    info = await fs.stat(target)
    assert info is not None
    assert info.type == "file"
    assert info.size > 0

    # Test readText
    text = await fs.readText(target)
    assert text == "line1\nline2\nline3\n"

    # Test editText
    edit_outcome = await fs.editText(target, {"oldString": "line2", "newString": "updated_line2"})
    assert edit_outcome.before == "line1\nline2\nline3\n"
    assert "updated_line2" in edit_outcome.after

    # Test listDir
    entries = await fs.listDir(tmpdir)
    assert len(entries) == 1
    assert entries[0].name == "test_file.txt"
    assert entries[0].type == "file"

    # Test contains
    assert fs.contains(tmpdir, target)


@pytest.mark.asyncio
async def test_tool_fs_read_write_edit(fs_env):
    ctx, tmpdir = fs_env
    tools: ToolsService = ctx.get("tools")
    file_path = os.path.join(tmpdir, "doc.txt")

    # 1. Write tool
    res_write = await tools.execute_tool("write", {"file_path": file_path, "content": "alpha\nbeta\ngamma\ndelta\n"})
    assert "<path>" in res_write
    assert "<type>file</type>" in res_write
    assert "Created file" in res_write

    # 2. Read tool
    res_read = await tools.execute_tool("read", {"file_path": file_path, "offset": 1, "limit": 2})
    assert "<path>" in res_read
    assert "1  alpha" in res_read
    assert "2  beta" in res_read

    # 3. Edit tool
    res_edit = await tools.execute_tool("edit", {"file_path": file_path, "old_string": "beta", "new_string": "BETA"})
    assert "has been updated successfully" in res_edit

    # Read again
    res_read2 = await tools.execute_tool("read", {"file_path": file_path})
    assert "BETA" in res_read2


@pytest.mark.asyncio
async def test_tool_fs_schema_registered(fs_env):
    ctx, _ = fs_env
    tools: ToolsService = ctx.get("tools")

    tool_read = tools.get_tool("read")
    assert tool_read is not None
    assert set(tool_read.parameters["properties"].keys()) == {"file_path", "offset", "limit"}

    tool_write = tools.get_tool("write")
    assert tool_write is not None
    assert set(tool_write.parameters["properties"].keys()) == {"file_path", "content"}

    tool_edit = tools.get_tool("edit")
    assert tool_edit is not None
    assert set(tool_edit.parameters["properties"].keys()) == {"file_path", "old_string", "new_string", "replace_all"}
