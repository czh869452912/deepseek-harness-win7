import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.tool_fs_search import FsSearchService, ToolFsSearchPlugin


@pytest.fixture
def search_workspace():
    tmp = tempfile.mkdtemp(prefix="dsh_search_test_")
    # Create sample file structure
    os.makedirs(os.path.join(tmp, "src", "sub"), exist_ok=True)
    with open(os.path.join(tmp, "src", "main.py"), "w", encoding="utf-8") as f:
        f.write("import os\nprint('hello from main')\n")
    with open(os.path.join(tmp, "src", "sub", "helper.py"), "w", encoding="utf-8") as f:
        f.write("def helper():\n    return 'hello from helper'\n")
    with open(os.path.join(tmp, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Sample Project\nThis is a sample readme.\n")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_glob_tool(search_workspace):
    svc = FsSearchService()
    res = svc.glob(pattern="*.py", cwd=search_workspace)
    assert "src/main.py" in res
    assert "src/sub/helper.py" in res
    assert "README.md" not in res


def test_grep_tool(search_workspace):
    svc = FsSearchService()
    res = svc.grep(pattern="hello", cwd=search_workspace)
    assert "src/main.py:" in res
    assert "Line 2: print('hello from main')" in res
    assert "src/sub/helper.py:" in res
    assert "Line 2:     return 'hello from helper'" in res


@pytest.mark.asyncio
async def test_fs_search_plugin_execution(search_workspace):
    ctx = Context()
    ctx.set_service("tools", ToolsService(ctx))
    ctx.plugin(ToolFsSearchPlugin)

    orig_cwd = os.getcwd()
    os.chdir(search_workspace)
    try:
        tools: ToolsService = ctx.get("tools")
        glob_res = await tools.execute_tool("glob", {"pattern": "*.md"})
        assert "README.md" in glob_res

        grep_res = await tools.execute_tool("grep", {"pattern": "Sample Project"})
        assert "README.md:" in grep_res
        assert "Line 1: # Sample Project" in grep_res
    finally:
        os.chdir(orig_cwd)
