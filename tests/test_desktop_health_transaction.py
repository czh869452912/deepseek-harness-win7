"""Actual installer generations, health rollback and interrupted publication."""
import json
from pathlib import Path
import shutil

import pytest

from dsh.boot import python_plugins as store
from dsh.boot import python_plugin_versions as versions
from dsh.boot.profile import init_profile, read_profile_manifest
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.profile_lease import ProfileLease
from dsh.host.desktop import health_transaction as health

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/python-echo'
NAME = '@example/python-echo'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    directory = tmp_path / 'profile'
    init_profile(str(directory), [])
    source = tmp_path / 'source'
    shutil.copytree(str(EXAMPLE), str(source))
    manifest_path = source / 'package.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['version'] = '0.2.0'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    return directory, source


def record(directory):
    return read_profile_manifest('desktop', str(directory)).get('dsh', {}).get('pythonPlugins', {}).get(NAME)


@pytest.mark.parametrize('operation', ('add', 'remove', 'upgrade'))
@pytest.mark.parametrize('healthy', (False, True))
def test_health_commit_or_exact_rollback(setup, operation, healthy):
    directory, source = setup
    if operation != 'add':
        store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    before = (directory / 'package.json').read_bytes()
    previous = record(directory)
    health.prepare(directory, operation, NAME if operation == 'remove' else str(source), NAME)
    assert (directory / health.JOURNAL).exists()
    if healthy:
        # Readiness commit works while the actual Host owns its shared OS lease.
        with ProfileLease(str(directory)):
            health.commit(directory)
        current = record(directory)
        if operation == 'remove':
            assert current is None
        else:
            assert current['version'] == '0.2.0'
        if operation == 'upgrade':
            archive = versions.archive_path(str(directory), NAME, previous)
            assert store.file_hashes(archive) == previous['files']
            versions.rollback(str(directory), NAME)
            assert record(directory)['version'] == previous['version']
    else:
        health.recover(directory)
        assert (directory / 'package.json').read_bytes() == before
        assert record(directory) == previous
        target = Path(store.destination(str(directory), NAME))
        assert store.file_hashes(str(target)) == previous['files'] if previous else not target.exists()
    assert not (directory / health.JOURNAL).exists()
    assert list((directory / health.WORK).iterdir()) == []


@pytest.mark.parametrize('after_move', (1, 2))
def test_interrupted_swap_recovers_previous_generation(setup, monkeypatch, after_move):
    directory, source = setup
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    before = (directory / 'package.json').read_bytes()
    original = store.replace_directory
    moves = []
    def interrupted(source_path, destination):
        result = original(source_path, destination)
        if str(directory / 'node_modules') in str(source_path) or str(directory / 'node_modules') in str(destination):
            moves.append(True)
            if len(moves) == after_move:
                raise RuntimeError('simulated process exit after publication move')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(store, 'replace_directory', interrupted)
        patch.setattr(health, '_rollback', lambda *_: None)
        with pytest.raises(RuntimeError, match='simulated process exit'):
            health.prepare(directory, 'upgrade', str(source), NAME)
    health.recover(directory)
    assert (directory / 'package.json').read_bytes() == before
    assert record(directory)['version'] == '0.1.0'


@pytest.mark.parametrize('damage', ('profile', 'plugin'))
def test_recovery_preserves_external_changes(setup, damage):
    directory, source = setup
    health.prepare(directory, 'add', str(source))
    if damage == 'profile':
        file = directory / 'package.json'
        file.write_text(file.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    else:
        file = Path(store.destination(str(directory), NAME)) / 'python/echo/plugin.py'
        file.write_text('# user change\n', encoding='utf-8')
    observation = file.read_bytes()
    with pytest.raises(RuntimeError, match='outside transaction'):
        health.recover(directory)
    assert file.read_bytes() == observation
    assert (directory / health.JOURNAL).exists()


def test_invalid_upgrade_preserves_profile_and_private_staging(setup):
    directory, source = setup
    store.install(str(directory), str(EXAMPLE), INSTALL_ANCHOR)
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='differs'):
        health.prepare(directory, 'upgrade', str(source), '@example/wrong')
    assert (directory / 'package.json').read_bytes() == before
    assert not (directory / health.JOURNAL).exists()
