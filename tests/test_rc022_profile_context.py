import asyncio
import json
from pathlib import Path
import pytest
from dsh.boot.profile_context import read_profile_patches, read_bundle_patches
from dsh.boot.profile_boot import ComposedProfile
from scripts import rc022_profile_context_probe as probe


def test_current_files_initial_snapshots_and_telemetry(tmp_path):
    probe.prepare(tmp_path)
    rows = asyncio.run(probe.native())
    assert len(rows) == 44 and all(row['unchanged'] for row in rows)
    for row in rows:
        if row['mode'] in ('invalid-user', 'invalid-home'):
            assert row['error']
            continue
        assert not row['error']
        if row['mode'] in ('no-telemetry', 'bundle-selection'):
            assert row['entries'] == []
        else:
            assert row['entries'][0]['disabled'] is (row['env'] in ('0', 'false'))
    initial = next(row for row in rows if row['mode'] == 'initial')
    assert initial['entries'][0]['config']['value'] == 'initial-user'
    edited = next(row for row in rows if row['mode'] == 'edited-bundle')
    assert edited['patches'][0]['insert'][0]['config']['value'] == 'edited-bundle'
    snapshot = next(row for row in rows if row['mode'] == 'edited-initial')
    assert snapshot['patches'][0]['insert'][0]['config']['value'] == 'bundle'


def test_bundle_read_skips_canonical_user_layer_but_complete_read_uses_custom_path(tmp_path):
    context, _ = probe.stage(tmp_path, 'invalid-canonical')
    assert read_bundle_patches('probe', context)
    assert read_profile_patches('probe', context)
    Path(context['patchPath']).write_text('{}', encoding='utf-8')
    assert read_bundle_patches('probe', context)
    with pytest.raises(RuntimeError): read_profile_patches('probe', context)


def test_composed_profile_keeps_overlay_input_and_captures_privacy_switch(tmp_path):
    context, initial = probe.stage(tmp_path, 'current')
    overlays = [dict(id='session-telemetry-otel', disabled=False)]
    value = ComposedProfile(initial, read_bundle_patches('probe', context, initial), [], overlays, 'false')
    assert value.all_patches()[-1] == dict(id='session-telemetry-otel', disabled=True)
    assert value.overlays == overlays == [dict(id='session-telemetry-otel', disabled=False)]
    value.all_patches()[0]['insert'][0]['config']['value'] = 'changed'
    assert initial.layers[0].patches[0]['insert'][0]['config']['value'] == 'bundle'


@pytest.mark.asyncio
async def test_launcher_live_reader_uses_explicit_home_and_current_bundle_files(tmp_path, monkeypatch):
    import dsh.boot.profile_boot as launcher
    from dsh.boot.app_boot import boot
    context, _ = probe.stage(tmp_path / 'owned', 'current')
    active = Path(context['dir']); canonical = active / 'cordis.patch.yml'
    canonical.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(launcher, 'INSTALL_ANCHOR', context['installAnchor'])
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'other-home'))
    captured = []
    async def watch(ctx, options): captured.append(options)
    async def wrapped(name, root_config, patches, setup):
        def host(ctx):
            setup(ctx); ctx.provide('hmr', object())
        return await boot(name, root_config, patches, host)
    monkeypatch.setattr(launcher, 'watch_user_patches', watch)
    monkeypatch.setattr(launcher, 'boot', wrapped)
    result = await launcher.run_profile(dict(profile='active', dsh_home=context['home'], wait_for_exit=False))
    try:
        ctx = result['ctx']
        assert [row['filename'] for row in captured] == [str(canonical), str(Path(context['home']) / 'cordis.patch.yml')]
        bundle = active / 'node_modules/selected/patch.yml'
        bundle.write_text(json.dumps([dict(insert=[dict(id='new', name='cordis:unused')])]), encoding='utf-8')
        monkeypatch.delenv('DSH_TELEMETRY_DISABLED')
        patches = captured[0]['compose']()
        assert patches[0]['insert'][0]['id'] == 'new'
        # The explicit home layer still contains one disable; no second
        # hard-disable is generated when the current bundle has no such row.
        assert len([row for row in patches if row.get('id') == 'session-telemetry-otel']) == 1
        assert ctx.get('profileContext')['home'] == context['home']
        assert ctx.get('profileContext')['telemetryDisabledEnv'] == '1'
    finally:
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()
