import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin, FsSearchService
from dsh.fs.tool_fs_search.glob import sample_across_top_level
from dsh.fs.tool_fs_search.grep import validate_include


def test_sample_across_top_level_distribution():
    paths = ["v/a", "v/b", "v/c", "v/d", "src/e", "guide/f"]
    res = sample_across_top_level(paths, 3)
    assert res["shown"] == 3
    assert res["total"] == 3
    assert res["items"] == ["v/a", "src/e", "guide/f"]


def test_sample_across_top_level_with_root():
    paths = [
        "workspace/vendor/a.ts",
        "workspace/vendor/b.ts",
        "workspace/source/c.ts",
        "workspace/guides/d.md",
    ]
    res = sample_across_top_level(paths, 3, root="workspace")
    assert res["shown"] == 3
    assert res["total"] == 3
    assert res["items"] == ["workspace/vendor/a.ts", "workspace/source/c.ts", "workspace/guides/d.md"]


def test_validate_include_errors():
    with pytest.raises(ValueError, match="include must be a non-empty glob when given"):
        validate_include("   ")

    with pytest.raises(ValueError, match="include must be a positive glob filter"):
        validate_include("!*.ts")

    with pytest.raises(ValueError, match="include must be one glob, not a comma-separated list"):
        validate_include("*.ts,*.js")

    validate_include("*.{ts,js}")


@pytest.fixture
def search_dir():
    d = tempfile.mkdtemp(prefix="dsh-search-test-")
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    os.makedirs(os.path.join(d, "docs"), exist_ok=True)
    with open(os.path.join(d, "src", "main.py"), "w", encoding="utf-8") as f:
        f.write("def hello():\n    print('Hello World')\n")
    with open(os.path.join(d, "docs", "README.md"), "w", encoding="utf-8") as f:
        f.write("# Hello Documentation\nWelcome!\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.mark.asyncio
async def test_glob_tool_execution(search_dir):
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    search_plugin = ToolFsSearchPlugin()
    search_plugin.apply(ctx)

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute_tool("glob", {
        "pattern": "*.py",
        "path": search_dir,
    })
    assert "src/main.py" in res or "main.py" in res


@pytest.mark.asyncio
async def test_grep_tool_execution(search_dir):
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    search_plugin = ToolFsSearchPlugin()
    search_plugin.apply(ctx)

    tools_svc = ctx.get("tools")
    res = await tools_svc.execute_tool("grep", {
        "pattern": "Hello",
        "path": search_dir,
    })
    assert "Found 2 matches" in res or "main.py" in res