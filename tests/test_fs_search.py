import asyncio
import os
import shutil
import tempfile
from types import SimpleNamespace

import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.fs.tool_fs_search import ToolFsSearchPlugin, sample_across_top_level
from dsh.subprocess import LocalSubprocessRuntime


class PromptService:
    def section(self, *args, **kwargs):
        return lambda: None


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


def _agent_at(path, ctx=None):
    return SimpleNamespace(ctx=ctx, session=SimpleNamespace(header=SimpleNamespace(id="direct", cwd=path)))


async def _mount_search():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("systemPrompt", PromptService())
    LocalSubprocessRuntime(ctx)
    fiber = ctx.registry.plugin(
        ToolFsSearchPlugin,
        {"sampleOverCapGlobResults": True},
        parent_ctx=ctx,
    )
    await fiber
    return ctx, tools, fiber


@pytest.mark.asyncio
async def test_glob_tool(search_workspace):
    _ctx, tools, fiber = await _mount_search()
    try:
        result = await tools.execute(ToolExecutionInput(
            "glob-direct", "glob", {"pattern": "*.py"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        assert os.path.join("src", "main.py") in result.value["paths"]
        assert os.path.join("src", "sub", "helper.py") in result.value["paths"]
        assert "README.md" not in result.value["paths"]
    finally:
        await fiber.dispose()


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


@pytest.mark.asyncio
async def test_grep_tool(search_workspace):
    _ctx, tools, fiber = await _mount_search()
    try:
        result = await tools.execute(ToolExecutionInput(
            "grep-direct", "grep", {"pattern": "hello"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        rendered = "".join(block["text"] for block in result.content)
        assert "Found 2 matches" in rendered
        assert os.path.join("src", "main.py") in rendered
        assert "Line 2: print('hello from main')" in rendered
        assert os.path.join("src", "sub", "helper.py") in rendered
        assert "Line 2:     return 'hello from helper'" in rendered
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_grep_options(search_workspace):
    _ctx, tools, fiber = await _mount_search()
    try:
        sensitive = await tools.execute(ToolExecutionInput(
            "case", "grep", {"pattern": "HELLO"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        assert "No matches found" in "".join(block["text"] for block in sensitive.content)

        included = await tools.execute(ToolExecutionInput(
            "include", "grep", {"pattern": "print\\('hello", "include": "*.py"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        rendered = "".join(block["text"] for block in included.content)
        assert "Found 1 match" in rendered
        assert os.path.join("src", "main.py") in rendered
    finally:
        await fiber.dispose()



@pytest.mark.asyncio
async def test_fs_search_plugin_execution(search_workspace):
    _ctx, tools, fiber = await _mount_search()
    try:
        glob_result = await tools.execute(ToolExecutionInput(
            "plugin-glob", "glob", {"pattern": "*.md"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        assert "README.md" in glob_result.value["paths"]

        grep_result = await tools.execute(ToolExecutionInput(
            "plugin-grep", "grep", {"pattern": "Sample Project"},
            agent=_agent_at(search_workspace, fiber.ctx), signal=asyncio.Event(),
        ))
        rendered = "".join(block["text"] for block in grep_result.content)
        assert "Found 1 match" in rendered
        assert "README.md" in rendered
        assert "Line 1: # Sample Project" in rendered
    finally:
        await fiber.dispose()
