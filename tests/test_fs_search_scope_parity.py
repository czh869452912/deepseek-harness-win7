import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.fs.tool_fs_search import ToolFsSearchPlugin


class PromptService:
    def section(self, *_args, **_kwargs):
        return lambda: None


class SubprocessService:
    pass


@pytest.mark.asyncio
async def test_fs_search_registers_tools_in_plugin_fiber_scope():
    """The TS plugin's ctx.tools is caller-bound; raw ctx.get leaks to root."""
    root = Context()
    tools = ToolsService(root)
    root.set_service("tools", tools)
    root.set_service("systemPrompt", PromptService())
    root.set_service("subprocess", SubprocessService())

    fiber = root.registry.plugin(
        ToolFsSearchPlugin,
        config={"sampleOverCapGlobResults": False},
        parent_ctx=root,
    )
    await fiber
    try:
        assert tools.get_tool("glob", fiber.ctx) is not None
        assert tools.get_tool("grep", fiber.ctx) is not None
        # Registration must be scoped, not visible from the root catalog.
        assert tools.get_tool("glob", root) is None
        assert tools.get_tool("grep", root) is None
    finally:
        await fiber.dispose()

