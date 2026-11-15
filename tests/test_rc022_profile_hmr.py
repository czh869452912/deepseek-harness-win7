import asyncio
import copy
import json

import pytest

from scripts.rc022_profile_hmr_probe import observe


def test_manifest_reload_metadata_is_inert_and_profiles_select_hmr_through_yaml(tmp_path):
    rows = observe(tmp_path/'contracts')
    assert len(rows) == 13
    assert all(not row['field'] and row['unchanged'] for row in rows if row['kind']=='legacy')
    retired = next(row['profile'] for row in rows if row['kind']=='retired')
    assert retired == dict(bundles=['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-headless'],
                           patchReload='retained-extension')
    by_mode = {row['mode']:row['row'] for row in rows if row['kind']=='row'}
    assert by_mode['sdk-minimal'] is None
    assert by_mode['web-app']['config'] == dict(root=[])
    assert all(by_mode[mode]['disabled'] is True for mode in ('headless','sdk-app','acp-app'))


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled', [False, True])
async def test_actual_launcher_obeys_the_hmr_row_without_manifest_fallback(tmp_path, disabled):
    from dsh.boot.app_boot import load_overlay_patches
    from dsh.boot.profile import init_profile
    from dsh.boot.profile_boot import run_profile
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    from scripts.rc022_profile_hmr_probe import ROOT
    directory = tmp_path/'profiles/demo'
    init_profile(str(directory), [])
    manifest = directory/'package.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['dsh']['profile']['patchReload'] = 'live' if disabled else 'startup'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    source = directory/'probe.py'
    source.write_text('def apply(ctx, config):\n    ctx.provide("watchedValue", config["value"])\n', encoding='utf-8')
    base = load_overlay_patches('test', str(ROOT/'packages/bundle/base/cordis.patch.yml'))[0]['insert']
    selected = [copy.deepcopy(row) for row in base if row.get('id') in ('timer','hmr')]
    next(row for row in selected if row['id']=='hmr')['disabled'] = disabled
    selected.append(dict(id='probe', name='./probe.py', config=dict(value='initial')))
    patch = directory/'cordis.patch.yml'
    rows = [dict(insert=selected)]
    patch.write_text(json.dumps(rows), encoding='utf-8')
    launched = await asyncio.wait_for(run_profile(dict(profile='demo', dshHome=str(tmp_path),
        environment=LaunchEnvironmentSnapshot([]), args=[], waitForExit=False)), 20)
    ctx = launched['ctx']
    try:
        hmr = ctx.get('hmr')
        assert (hmr is None) is disabled
        assert len([entry for entry in ctx.loader.entries() if entry.options.get('name')=='@deepseek-ai/dsh-hmr']) == 1
        assert ctx.get('watchedValue') == 'initial'
        rows[0]['insert'][-1]['config']['value'] = 'edited'
        patch.write_text(json.dumps(rows), encoding='utf-8')
        if disabled:
            await asyncio.sleep(.1)
            assert ctx.get('watchedValue') == 'initial'
        else:
            for unused in range(500):
                if ctx.get('watchedValue') == 'edited':
                    break
                await asyncio.sleep(.01)
            assert ctx.get('watchedValue') == 'edited'
            await hmr.runExclusive(lambda: None)
    finally:
        await ctx.fiber.dispose()
        await ctx.fiber.await_settled()
