from dsh.harness import build_harness
import asyncio
import pytest

from dsh.cordis.fiber import FiberState


def test_build_harness_minimal_mode():
    ctx = asyncio.run(build_harness(mode="minimal"))

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "persona" in plugins
    assert "fs-local" in plugins
    assert "str-replace-editor" in plugins

    tools = [t.name for t in ctx.tools.list_tools()]
    assert "str_replace_editor" in tools
    assert "pwsh" in tools or "bash" in tools


@pytest.mark.asyncio
async def test_build_harness_settles_every_loader_task():
    """
    boot/harness settlement: after `build_harness` returns, the loader tree owns
    no pending task and every mounted entry fiber has settled ACTIVE.
    """
    ctx = await build_harness(mode="minimal")
    loader = ctx.get("loader")
    assert loader is not None
    assert loader.get_tasks() == []

    for entry in loader.entries():
        fiber = entry.fiber
        if fiber is None:
            continue
        assert fiber.state == FiberState.ACTIVE

    pending = [
        task for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


def test_build_harness_creative_mode():
    ctx = asyncio.run(build_harness(mode="creative"))

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "cordis-manager" in plugins

    tools = [t.name for t in ctx.tools.list_tools()]
    assert "cordis_list_plugins" in tools
    assert "cordis_inspect_context" in tools
    assert "cordis_unload_plugin" in tools
    assert "cordis_dump_config" in tools
