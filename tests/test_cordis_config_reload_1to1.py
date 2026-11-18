"""Current raw publication and ownership in vendor/loader/src/config/{entry,tree}.ts.

The old transaction assertions predated the pinned best-effort Loader contract.
Rejected activation retains the candidate options and owner.
"""
import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin


class ConfigurablePlugin(Plugin):
    name = 'configurable-plugin'

    def apply(self, ctx):
        if self.config.get('fail'):
            raise ValueError('Candidate config failed')
        ctx.provide('observed_cfg', dict(self.config))


async def fixture():
    ctx = Context()
    await ctx.plugin(Loader)
    ctx.loader.register_plugin_class('configurable-plugin', ConfigurablePlugin)
    return ctx


@pytest.mark.asyncio
async def test_failed_entry_update_keeps_raw_candidate_and_recovers():
    ctx = await fixture()
    try:
        await ctx.loader.create(dict(id='target', name='configurable-plugin', config={'val': 1}))
        await ctx.loader.await_()
        entry = ctx.loader.resolve('target')
        fiber = entry.fiber
        assert ctx.get('observed_cfg') == {'val': 1}
        with pytest.raises(ValueError, match='Candidate config failed'):
            await entry.update({'config': {'val': 2, 'fail': True}})
        assert entry.options['config'] == {'val': 2, 'fail': True}
        assert entry.fiber is fiber and fiber.state == FiberState.FAILED
        assert ctx.get('observed_cfg') is None
        await entry.update({'config': {'val': 3}})
        await ctx.loader.await_()
        assert entry.fiber is fiber and fiber.state == FiberState.ACTIVE
        assert ctx.get('observed_cfg') == {'val': 3}
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disabling_an_ordinary_parent_releases_children_and_reenable_recreates_them():
    ctx = await fixture()
    try:
        # The separate group:true marker is always enabled in the current
        # contract; an ordinary Group plugin may itself be disabled.
        await ctx.loader.create(dict(id='parent', name='cordis:group', config=[
            dict(id='child', name='configurable-plugin', config={'val': 100})]))
        await ctx.loader.await_()
        parent = ctx.loader.resolve('parent')
        child = ctx.loader.resolve('child')
        original = child.fiber
        assert original.state == FiberState.ACTIVE
        await parent.update({'disabled': True})
        await ctx.loader.await_()
        assert 'child' not in ctx.loader.store
        assert child.fiber is original and original.uid is None
        assert ctx.get('observed_cfg') is None
        await parent.update({'disabled': False})
        await ctx.loader.await_()
        recreated = ctx.loader.resolve('child')
        assert recreated.fiber is not original and recreated.fiber.state == FiberState.ACTIVE
        assert ctx.get('observed_cfg') == {'val': 100}
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_programmatic_move_retains_destination_and_candidate_options():
    ctx = await fixture()
    try:
        await ctx.loader.create(dict(id='destination', name='cordis:group', group=True, config=[]))
        await ctx.loader.create(dict(id='target', name='configurable-plugin', config={'val': 1}))
        await ctx.loader.await_()
        entry = ctx.loader.resolve('target')
        source = entry.parent
        destination = ctx.loader.resolve('destination').subgroup
        with pytest.raises(ValueError, match='Candidate config failed'):
            await ctx.loader.update('target', {'config': {'fail': True}}, parent_id='destination')
        assert entry.parent is destination
        assert entry.options in destination.data and entry.options not in source.data
        assert entry.options['config'] == {'fail': True}
        assert entry.fiber.state == FiberState.FAILED
        await ctx.loader.update('target', {'config': {'val': 2}})
        await ctx.loader.await_()
        assert entry.parent is destination and entry.fiber.state == FiberState.ACTIVE
        assert ctx.get('observed_cfg') == {'val': 2}
    finally:
        await ctx.fiber.dispose()
