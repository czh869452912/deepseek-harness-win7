import pytest

from dsh.harness import build_harness, initialize_harness
from dsh.cordis.fiber import FiberState


def test_build_harness_minimal_mode():
    ctx = build_harness(mode="minimal")

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "persona" in plugins
    assert "fs-local" in plugins
    assert "str-replace-editor" in plugins

    scope = next(f.ctx for f in ctx.registry.list_fibers() if f.name == "@deepseek-ai/dsh-tools")
    tools = [t.name for t in ctx.tools.list_tools(scope=scope)]
    assert "str_replace_editor" in tools
    assert "pwsh" in tools or "bash" in tools


def test_build_harness_creative_mode():
    ctx = build_harness(mode="creative")

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "cordis-manager" in plugins

    scope = next(f.ctx for f in ctx.registry.list_fibers() if f.name == "@deepseek-ai/dsh-tools")
    tools = [t.name for t in ctx.tools.list_tools(scope=scope)]
    assert "cordis_list_plugins" in tools
    assert "cordis_inspect_context" in tools
    assert "cordis_unload_plugin" in tools
    assert "cordis_dump_config" in tools


@pytest.mark.asyncio
async def test_minimal_web_harness_activates_tool_chain_without_system_prompt():
    ctx = build_harness(mode="minimal", enable_web=True, verbose=False)
    await initialize_harness(ctx)

    tools_fiber = next(
        fiber for runtime in ctx.registry._runtimes.values()
        for fiber in runtime.fibers
        if getattr(fiber, "name", None) == "@deepseek-ai/dsh-tools"
    )
    assert tools_fiber.state == FiberState.ACTIVE
    assert ctx.get("tools") is not None
