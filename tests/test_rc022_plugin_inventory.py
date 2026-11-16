import json

import pytest

from dsh.boot.plugin_packages import PluginPackages
from dsh.cordis import Context, Loader, Plugin
from dsh.host.plugin_inventory.current import CurrentPluginInventory
from dsh.typert.remote import remote_methods
from scripts.rc022_plugin_inventory_probe import observe


@pytest.mark.asyncio
async def test_inventory_optional_services_phases_diagnostics_and_fresh_reads():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 10
    assert all(row['withdrawn'] for row in rows.values())
    full = rows['full']['result']
    assert [row['fiberPhase'] for row in full['first']['entries']] == [
        'pending', 'loading', 'active', 'failed', None, 'unloading', None]
    assert full['first']['entries'][3]['diagnostic'] == 'startup failure'
    assert len(full['second']['entries']) == len(full['first']['entries']) + 1
    assert full['first']['managementAvailable'] is True
    assert 'managementAvailable' not in rows['no-manager']['result']['first']
    assert 'agentPresets' not in rows['no-presets']['result']['first']
    assert all('meta' not in row for row in rows['no-packages']['result']['first']['entries'])
    assert rows['metadata-error']['result']['original']
    assert rows['preset-error']['result']['original']
    assert rows['failed-value']['result']['first']['entries'][3]['diagnostic'] == '[object Object]'
    assert 'diagnostic' not in rows['failed-success']['result']['first']['entries'][3]


@pytest.mark.asyncio
async def test_real_loader_failed_recovery_disable_and_service_withdrawal():
    ctx = Context()
    try:
        await ctx.plugin(Loader)
        def active(owner, config):
            if config.get('fail'):
                raise RuntimeError('actual startup failure')
        class Pending(Plugin):
            inject = ['neverReady']
            def apply(self, owner):
                raise AssertionError('pending plugin must not execute')
        ctx.loader.builtins.update(active=active, pending=Pending)
        owner = await ctx.plugin(CurrentPluginInventory)
        service = ctx.pluginInventory
        assert remote_methods(service) == [dict(method='list', invocation=dict(kind='direct'))]
        active_id = await ctx.loader.create(dict(id='active', name='cordis:active', config={}))
        await ctx.loader.create(dict(id='pending', name='cordis:pending'))
        await ctx.loader.create(dict(id='disabled', name='cordis:active', disabled=True))
        await ctx.loader.wait()
        first = await service.list()
        assert [(row['entryId'], row['enabled'], row['fiberPhase']) for row in first['entries']] == [
            (active_id, True, 'active'), ('pending', True, 'pending'), ('disabled', False, None)]
        entry = ctx.loader.resolve(active_id)
        with pytest.raises(RuntimeError, match='actual startup failure'):
            await entry.update(dict(config=dict(fail=True)))
        with pytest.raises(RuntimeError, match='actual startup failure'):
            await entry.fiber
        assert (await service.list())['entries'][0]['diagnostic'] == 'actual startup failure'
        await entry.update(dict(config=dict(fail=False)))
        await entry.fiber
        assert 'diagnostic' not in (await service.list())['entries'][0]
        await entry.update(dict(disabled=True))
        assert (await service.list())['entries'][0]['fiberPhase'] is None
        await entry.update(dict(disabled=False))
        await entry.fiber
        assert (await service.list())['entries'][0]['fiberPhase'] == 'active'
        await owner.dispose()
        assert ctx.get('pluginInventory') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disabled_package_metadata_does_not_execute_plugin(tmp_path):
    root = tmp_path / 'metadata'
    package = root / 'node_modules' / 'local-plugin'
    (package / 'locale').mkdir(parents=True)
    (package / 'package.json').write_text(json.dumps(dict(name='local-plugin', exports={
        './feature': './index.js', './feature/locale/*.json': './locale/*.json'})), encoding='utf-8')
    (package / 'index.js').write_text('throw new Error("must not execute")', encoding='utf-8')
    (package / 'locale' / 'en.json').write_text(json.dumps(dict(meta=dict(title='Local plugin'))), encoding='utf-8')
    ctx = Context()
    try:
        ctx.baseUrl = (root / 'entry.mjs').as_uri()
        await ctx.plugin(Loader)
        await ctx.plugin(PluginPackages)
        await ctx.plugin(CurrentPluginInventory)
        await ctx.loader.create(dict(id='local', name='local-plugin/feature', disabled=True))
        assert (await ctx.pluginInventory.list())['entries'] == [dict(
            entryId='local', moduleName='local-plugin/feature', enabled=False,
            fiberPhase=None, meta=dict(title=dict(en='Local plugin')))]
    finally:
        await ctx.fiber.dispose()
