"""Formal profile startup replaces the retired flat harness."""
import importlib.util
import pytest
from canonical_web_fixture import web_context, close_web_context
from dsh.cordis.fiber import FiberState


def test_flat_harness_entry_is_retired():
    assert importlib.util.find_spec('dsh.harness') is None


@pytest.mark.asyncio
async def test_formal_web_settles_loader_entries(tmp_path):
    ctx = await web_context(tmp_path)
    try:
        loader = ctx.get('loader')
        assert loader.get_tasks() == []
        assert all(e.fiber.state == FiberState.ACTIVE for e in loader.entries() if e.fiber is not None)
        assert ctx.get('sessionController') is not None
        assert ctx.get('tools') is not None
    finally:
        await close_web_context(ctx)
    assert ctx.get('sessionController') is None
    assert ctx.registry.list_fibers() == []
