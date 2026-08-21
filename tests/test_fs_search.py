import os
import shutil
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.tool_fs_search import FsSearchService, ToolFsSearchPlugin, sample_across_top_level


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


def test_sample_across_top_level():
    paths = [
        "src/a.ts",
        "src/b.ts",
        "src/c.ts",
        "packages/pkg1/index.ts",
        "packages/pkg2/index.ts",
        "docs/readme.md",
    ]
    sampled = sample_across_top_level(paths, max_items=3, root=".")
    assert len(sampled["items"]) == 3
    assert sampled["shown"] == 3
    assert sampled["total"] == 3
    # Round robin picked one from src, one from packages, one from docs
    top_dirs = {p.split("/")[0] for p in sampled["items"]}
    assert top_dirs == {"src", "packages", "docs"}


def test_grep_tool(search_workspace):
    svc = FsSearchService()
    res = svc.grep(pattern="hello", cwd=search_workspace)
    assert "Found 2 matches" in res
    assert "src/main.py" in res
    assert "Line 2: print('hello from main')" in res
    assert "src/sub/helper.py" in res
    assert "Line 2:     return 'hello from helper'" in res


def test_grep_options(search_workspace):
    svc = FsSearchService()
    # Case sensitive
    res_sensitive = svc.grep(pattern="HELLO", case_sensitive=True, cwd=search_workspace)
    assert res_sensitive == "No matches found"

    # Fixed strings
    res_fixed = svc.grep(pattern="print('hello", fixed_strings=True, cwd=search_workspace)
    assert "Found 1 match" in res_fixed
    assert "src/main.py" in res_fixed


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
        assert "Found 1 match" in grep_res
        assert "README.md" in grep_res
        assert "Line 1: # Sample Project" in grep_res
    finally:
        os.chdir(orig_cwd)

