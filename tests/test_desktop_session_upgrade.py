"""Existing home upgrades through the actual Desktop/workspace composition."""
import json
from pathlib import Path

import pytest

from dsh.host.desktop.runtime import run_desktop_host
from dsh.core.abort import AbortController
from dsh.boot.session_compatibility import preserve_default_session_encoding
from dsh.session.jsonl_current import generationLogPath
from dsh.session.jsonl_zstd import compress_frame


def history(home, compression, version=0, identity='old-session'):
    # No cwd is represented by UNDEFINED, rather than a JSON null.
    from dsh.core.session.json import UNDEFINED
    path = Path(generationLogPath(str(home / 'sessions'), UNDEFINED, identity, version, compression))
    path.parent.mkdir(parents=True, exist_ok=True)
    header = dict(type='session', version=version, id=identity, createdAt=1, delegationDepth=0)
    if version >= 2:
        header['isSeeded'] = False
    data = (json.dumps(header) + '\n').encode('utf-8')
    path.write_bytes(compress_frame(data) if compression == 'zstd' else data)
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['none', 'zstd'])
async def test_existing_home_boots_and_cold_opens_without_rewriting_history(tmp_path, monkeypatch, compression):
    home = tmp_path / 'home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    old = history(home, compression)
    future = history(home, compression, 5, 'future-session')
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (old, future)}
    for _ in range(2):
        runtime = await run_desktop_host(tmp_path / 'profile')
        try:
            store = runtime.ctx.get('sessionPersistence')
            assert store.compression == compression
            assert [item['header']['id'] for item in await store.list()] == ['old-session']
            assert runtime.ctx.get('workspaceRegistry') is not None
            assert (await runtime.fetch(dict(url='dsh-app://app/index.html', method='GET', headers={}, signal=AbortController().signal)))['status'] == 200
        finally:
            await runtime.close()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (old, future)} == original
    assert not list((home / 'sessions').rglob('session.v4*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [False, True])
async def test_mixed_or_explicit_conflict_stays_an_error_and_releases_profile(tmp_path, monkeypatch, explicit):
    home = tmp_path / 'home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    old = history(home, 'none')
    if not explicit:
        history(home, 'zstd', 3, 'compressed-session')
    patches = [dict(id='session-persistence-jsonl', config=dict(root=str(home / 'sessions'), compression='zstd'))] if explicit else []
    with pytest.raises(Exception, match='configured for compression'):
        await run_desktop_host(tmp_path / 'profile', patches=patches)
    # Correcting the profile works after the failed boot; no process lease leaked.
    if not explicit:
        return
    runtime = await run_desktop_host(tmp_path / 'profile')
    await runtime.close()
    assert old.exists()


def test_custom_root_and_explicit_policy_are_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    history(tmp_path, 'none')
    base = dict(id='session-persistence-jsonl', name='@deepseek-ai/dsh-session-persistence-jsonl')
    for config in (dict(root=str(tmp_path / 'sessions')),
                   dict(root={'__jsExpr': "dshHomePath('sessions')"}, compression='zstd')):
        patches = [dict(insert=[dict(base, config=config)])]
        assert preserve_default_session_encoding(patches) == patches


@pytest.mark.asyncio
async def test_empty_home_still_defaults_to_zstd(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    runtime = await run_desktop_host(tmp_path / 'profile')
    try:
        assert runtime.ctx.get('sessionPersistence').compression == 'zstd'
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('surface,compression', [(surface, encoding) for surface in ('standard', 'creative', 'web', 'desktop') for encoding in ('none', 'zstd')] + [('minimal', 'none')])
async def test_shared_home_content_resume_migration_and_surface_cold_open(tmp_path, monkeypatch, surface, compression):
    from dsh.boot.profile_boot import run_profile
    from dsh.core.session.json import UNDEFINED
    from dsh.session.persistence import SessionAlreadyOwnedError
    home = tmp_path / 'shared-home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    cases = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/session_generation_cases.json').read_text(encoding='utf-8'))
    case = next(row for row in cases if row['case'] == 'generation/none/v0/publish')
    old = Path(generationLogPath(str(home / 'sessions'), UNDEFINED, 'generation', 0, compression))
    old.parent.mkdir(parents=True)
    data = case['raw'].encode('utf-8')
    first, body = data.split(b'\n', 1)
    old.write_bytes(compress_frame(first + b'\n') + compress_frame(body) if compression == 'zstd' else data)
    before = old.read_bytes(), old.stat().st_mtime_ns
    overlay = tmp_path / 'observe.yml'
    overlay.write_text('- id: headless-startup\n  disabled: true\n- id: headless-runner\n  disabled: true\n- id: sdk-app-startup\n  disabled: true\n- id: sdk-jsonrpc-server\n  disabled: true\n', encoding='utf-8')
    for cold in (False, True):
        if surface == 'desktop':
            result = await run_desktop_host(home / 'profiles/desktop')
            ctx = result.ctx
        else:
            result = await run_profile(dict(profile=surface, dshHome=str(home), patchFiles=[str(overlay)],
                args=['--no-open', '--port', '0'] if surface == 'web' else [], waitForExit=False))
            ctx = result['ctx']
        try:
            store = ctx.get('sessionPersistence')
            assert store.compression == compression
            reader = await store.open('generation', 'read')
            artifact = await reader.read()
            assert (await store.stat('generation'))['header']['version'] == 4
            assert any(event['type'] == 'system/message' for event in artifact['events'])
            await reader.close()
            current = Path(generationLogPath(store.root, UNDEFINED, 'generation', 4, compression))
            if not cold:
                assert not current.exists(), 'reading legacy content must not publish migration'
                writer = await store.open('generation', 'write')
                try:
                    with pytest.raises(SessionAlreadyOwnedError):
                        await store.open('generation', 'write')
                    count = len(artifact['events'])
                    await writer.append([dict(type='turn/start', seq=count, time=20, data=dict(turn=2))])
                finally:
                    await writer.close()
                assert current.is_file()
            else:
                assert artifact['events'][-1]['data']['turn'] == 2
                assert artifact['events'][-1]['type'] == 'turn/start'
            assert (old.read_bytes(), old.stat().st_mtime_ns) == before
        finally:
            if surface == 'desktop':
                await result.close()
            else:
                result['shutdown'].shutdown(0)
                await result['shutdown'].wait()


@pytest.mark.asyncio
@pytest.mark.parametrize('surface', ['standard', 'web', 'desktop'])
async def test_explicit_custom_root_recovers_a_mixed_default_without_touching_it(tmp_path, monkeypatch, surface):
    from dsh.boot.profile_boot import run_profile
    import yaml
    home = tmp_path / 'home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    originals = [history(home, 'none'), history(home, 'zstd', 3, 'other-session')]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in originals]
    custom = tmp_path / 'independent-home'
    history(custom, 'none', identity='custom-session')
    patches = [dict(id='headless-startup', disabled=True), dict(id='headless-runner', disabled=True),
               dict(id='session-persistence-jsonl', config=dict(root=str(custom / 'sessions'), compression='none'))]
    if surface == 'desktop':
        result = await run_desktop_host(home / 'profiles/desktop', patches=patches)
        ctx = result.ctx
    else:
        overlay = tmp_path / 'explicit.yml'
        overlay.write_text(yaml.safe_dump(patches), encoding='utf-8')
        result = await run_profile(dict(profile=surface, dshHome=str(home), patchFiles=[str(overlay)],
            args=['--no-open', '--port', '0'] if surface == 'web' else [], waitForExit=False))
        ctx = result['ctx']
    try:
        store = ctx.get('sessionPersistence')
        assert store.root == str(custom / 'sessions') and store.compression == 'none'
        assert [row['header']['id'] for row in await store.list()] == ['custom-session']
        assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in originals] == before
    finally:
        if surface == 'desktop':
            await result.close()
        else:
            result['shutdown'].shutdown(0)
            await result['shutdown'].wait()
