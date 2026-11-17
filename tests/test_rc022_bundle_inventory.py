import json

import pytest

from dsh.boot.plugin_bundle_metadata import official_bundle_install_target, OFFICIAL_CATALOG
from scripts.rc022_bundle_inventory_probe import observe


@pytest.mark.asyncio
async def test_portable_listing_scans_flattened_inventory_once_and_refreshes_next_request(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from dsh.boot import plugin_bundle_metadata as metadata, profile_boot
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.cordis import Context
    root = tmp_path / 'portable'
    anchor = root / 'apps/cli/package.json'
    anchor.parent.mkdir(parents=True)
    anchor.write_text(json.dumps(dict(name='installation', dependencies={'one':'*', 'two':'*'})), encoding='utf-8')
    directory = tmp_path / 'profile'; directory.mkdir()
    (directory / 'package.json').write_text(json.dumps(dict(name='profile', dsh=dict(profile=dict(bundles=[])))), encoding='utf-8')
    for name in ['one', 'two']:
        package = root / 'packages/bundle' / name; package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps(dict(name=name, version='1.0.0', dsh=dict(bundle=dict(patch='patch.yml')))), encoding='utf-8')
        (package / 'patch.yml').write_text('[]', encoding='utf-8')
    monkeypatch.setattr(metadata, '__file__', str(root / 'dsh/boot/plugin_bundle_metadata.py'))
    monkeypatch.setattr(profile_boot, '_CANDIDATE_ANCHORS', [str(anchor)])
    calls = []
    original = metadata._installation_resolver
    def counted(options):
        calls.append(dict(options))
        return original(options)
    monkeypatch.setattr(metadata, '_installation_resolver', counted)
    ctx = Context()
    ctx.set_service('loader', NS(entries=lambda: []))
    ctx.set_service('profileContext', dict(dir=str(directory), installAnchor=str(anchor), startedBundles=[]))
    await ctx.plugin(CurrentPluginManager)
    try:
        first = await ctx.pluginManager.listBundles()
        assert len(calls) == 1
        assert {row['name'] for row in first if row['availability'] == 'installation'} == {'one', 'two'}
        package = root / 'packages/bundle/two/package.json'
        value = json.loads(package.read_text(encoding='utf-8')); value['version'] = '2.0.0'
        package.write_text(json.dumps(value), encoding='utf-8')
        second = await ctx.pluginManager.listBundles()
        assert len(calls) == 2
        assert next(row['version'] for row in second if row['name'] == 'two') == '2.0.0'
        assert next(row['version'] for row in first if row['name'] == 'two') == '1.0.0'
        assert metadata._resolution_scope.get() is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_bundle_ownership_platform_selection_and_update_projection(tmp_path):
    observations = await observe(tmp_path)
    assert observations[0]['data']['catalog'] == OFFICIAL_CATALOG
    rows = {row['name']:row for row in observations[1:]}
    assert len(rows) == 14
    def bundle(mode, name='extra', phase='first'):
        return next(row for row in rows[mode][phase] if row['name'] == name)
    assert bundle('ordinary')['update'] == 'registry'
    assert bundle('ordinary')['rows'] == [dict(rowId='extra', moduleName='cordis:active', entryId='include:extra', meta=dict(title='row cordis:active'))]
    assert bundle('ordinary')['overrides'] == ['foreign']
    assert bundle('ordinary', 'core')['readOnlyReason'] == 'management-required'
    assert all(item['name'] != 'ordinary' for item in rows['ordinary']['first'])
    assert not rows['ordinary']['steps'][1]['result']['changed']
    assert rows['ordinary']['steps'][2]['selected'] == ['core', 'extra']
    assert rows['ordinary']['steps'][3]['result']['error']['code'] == 'management-required'
    assert bundle('shipped')['availability'] == 'installation'
    assert bundle('shipped')['version'] == '9.0.0'
    assert not bundle('shipped')['removable'] and 'source' not in bundle('shipped')
    assert bundle('platform')['error']['code'] == 'unsupported-platform'
    assert bundle('platform')['listedByDefault'] is False
    assert rows['platform']['steps'][2]['result']['changed'] is False
    assert bundle('incompatible')['error']['code'] == 'incompatible-version'
    assert 'error' not in bundle('exempted')
    assert bundle('invalid-listing')['meta']['error'] == 'dsh.bundle.listedByDefault must be a boolean'
    assert bundle('missing-selected', 'missing')['availability'] == 'missing'
    assert bundle('not-bundle', 'ordinary')['error']['code'] == 'not-bundle'
    assert bundle('source-forms', 'git-pinned')['update'] == 'git'
    for name in ('git-branch', 'alias', 'local'):
        assert 'update' not in bundle('source-forms', name)
    assert bundle('protected-broken', 'core')['readOnlyReason'] == 'management-required'
    assert bundle('null-version')['version'] is None
    assert all(step['result']['application'] == 'restart-required' for step in rows['startup']['steps'][:3])


@pytest.mark.parametrize('defect', [None, 'missing-main', 'private', 'version', 'missing-patch', 'duplicate'])
def test_official_source_target_requires_complete_public_built_package(tmp_path, defect):
    root = tmp_path/'checkout'
    anchor = root/'apps/cli/package.json'
    anchor.parent.mkdir(parents=True)
    anchor.write_text(json.dumps(dict(name='@deepseek-ai/dsh', dependencies=dict(boot='workspace:*'))), encoding='utf-8')
    (root/'package.json').write_text(json.dumps(dict(name='@deepseek-ai/dsh-root')), encoding='utf-8')
    package = root/'packages/extra/offered'
    package.mkdir(parents=True)
    manifest = dict(name='offered', version='1.0.0', main='index.js', dsh=dict(bundle=dict(patch='patch.yml')))
    if defect == 'private':manifest['private'] = True
    if defect == 'version':manifest['version'] = '2.0.0'
    (package/'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    if defect != 'missing-main':(package/'index.js').write_text('throw new Error("must not import")', encoding='utf-8')
    if defect != 'missing-patch':(package/'patch.yml').write_text('[]', encoding='utf-8')
    if defect == 'duplicate':
        duplicate = root/'packages/other/offered'
        duplicate.mkdir(parents=True)
        (duplicate/'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    if defect is None:
        assert official_bundle_install_target('offered', str(anchor), '1.0.0') == dict(spec='link:'+str(package.resolve()), version='1.0.0')
    else:
        with pytest.raises(RuntimeError, match='Official bundle offered:'):
            official_bundle_install_target('offered', str(anchor), '1.0.0')


@pytest.mark.asyncio
async def test_bundle_selection_reconciles_real_include_loader_and_hmr(tmp_path):
    from types import SimpleNamespace as NS
    from dsh.boot.app_boot import boot
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.boot.profile_context import read_profile_patches
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    directory = tmp_path/'profile'
    directory.mkdir()
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
    write(tmp_path/'package.json', dict(name='installation'))
    write(directory/'package.json', dict(name='profile', dependencies=dict(extra='1.0.0'),
        dsh=dict(profile=dict(bundles=['core', 'extra']))))
    for name, rows in [('core', [dict(id='manager', name='cordis:manager')]),
                       ('extra', [dict(id='active', name='cordis:active')])]:
        package = directory/'node_modules'/name
        package.mkdir(parents=True)
        write(package/'package.json', dict(name=name, version='1.0.0', dsh=dict(bundle=dict(patch='patch.yml'))))
        write(package/'patch.yml', [dict(insert=rows)])
    write(directory/'cordis.yml', [])
    write(directory/'cordis.patch.yml', [])
    profile = dict(name='test', dir=str(directory), patchPath=str(directory/'cordis.patch.yml'),
        installAnchor=str(tmp_path/'package.json'), cwd=str(tmp_path), home=str(tmp_path),
        startedBundles=['core', 'extra'], overlays=[])
    def setup(ctx):
        ctx.provide('profileContext', profile)
        ctx.provide('appReady', NS(onReady=lambda listener:(listener(), lambda:None)[1]))
        ctx.loader.builtins.update(manager=CurrentPluginManager, active=lambda owner, config:owner.provide('bundleProbe', True))
    ctx = await boot('test', str(directory/'cordis.yml'), read_profile_patches('test', profile), setup)
    try:
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, dict(root=[], ignored=[], debounce=0))
        await ctx.hmr.runExclusive(lambda:None)
        assert ctx.get('bundleProbe') is True
        result = await ctx.pluginManager.setBundleEnabled('extra', False)
        assert result['changed'] and result['application'] == 'applied'
        assert ctx.get('bundleProbe') is None
        with pytest.raises(KeyError):
            ctx.loader.resolve('include:active')
        assert not (await ctx.pluginManager.setBundleEnabled('extra', False))['changed']
        result = await ctx.pluginManager.setBundleEnabled('extra', True)
        assert result['changed'] and result['application'] == 'applied'
        assert ctx.get('bundleProbe') is True
        await ctx.loader.resolve('include:active').fiber
        assert json.loads((directory/'package.json').read_text(encoding='utf-8'))['dependencies'] == dict(extra='1.0.0')
    finally:
        await ctx.fiber.dispose()
