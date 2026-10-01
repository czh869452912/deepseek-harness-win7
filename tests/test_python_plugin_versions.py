"""Actual version swaps, canonical restarts and interrupted-process recovery."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
from apps.cli import plugin as plugin_cli
from dsh.boot import python_plugins as store
from dsh.boot import python_plugin_versions as versions
from dsh.boot.profile import read_profile_manifest
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.profile_boot import run_profile
from test_python_plugin_distribution import profile, boot, close, echo, EXAMPLE, PACKAGE, ROOT


def source_version(tmp_path, version='0.2.0', text='Version two: ', broken=False):
    source = tmp_path / ('source-' + version)
    shutil.copytree(str(EXAMPLE), str(source))
    path = source / 'package.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['version'] = version
    path.write_text(json.dumps(manifest), encoding='utf-8')
    (source / 'python/echo/formatting.py').write_text('def format_echo(text):\n    return ' + repr(text) + ' + text\n', encoding='utf-8')
    if broken:
        (source / 'python/echo/plugin.py').write_text("raise RuntimeError('bad release import')\n", encoding='utf-8')
    return source


def installed(directory):
    return directory / 'node_modules/@example/python-echo'


def record(directory):
    return read_profile_manifest('dsh', str(directory))['dsh']['pythonPlugins'][PACKAGE]


def zip_source(source, path):
    with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in source.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                archive.write(str(file), 'wrapped/' + file.relative_to(source).as_posix())
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize('container', ['directory', 'zip'])
async def test_upgrade_restart_named_rollback_and_newer_rollback_without_node(profile, tmp_path, container):
    home, directory = profile
    patch = (directory / 'cordis.patch.yml').read_bytes()
    sys_path = list(sys.path)
    assert plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)]) == 0
    first = await boot(home)
    try:
        assert await echo(first['ctx']) == 'Python echo: hello'
    finally:
        await close(first)
    source = source_version(tmp_path)
    source = zip_source(source, tmp_path / 'version-two.zip') if container == 'zip' else source
    assert plugin_cli.run_plugin('python-test', ['upgrade', str(source)]) == 0
    assert record(directory)['version'] == '0.2.0'
    history = record(directory)['history']
    assert [entry['version'] for entry in history] == ['0.1.0']
    assert Path(versions.archive_path(str(directory), PACKAGE, history[0])).is_dir()
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'restart') == 'Version two: restart'
        assert list(sys.path) == sys_path
        with pytest.raises(RuntimeError, match='profile is in use'):
            plugin_cli.run_plugin('python-test', ['rollback', PACKAGE])
        assert versions.versions(str(directory), PACKAGE)['versions'][0]['current']
    finally:
        await close(result)
    assert plugin_cli.run_plugin('python-test', ['rollback', PACKAGE, '0.1.0']) == 0
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'rollback') == 'Python echo: rollback'
    finally:
        await close(result)
    assert record(directory)['version'] == '0.1.0'
    assert plugin_cli.run_plugin('python-test', ['rollback', PACKAGE]) == 0
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'again') == 'Version two: again'
    finally:
        await close(result)
    assert record(directory)['version'] == '0.2.0'
    assert (directory / 'cordis.patch.yml').read_bytes() == patch
    manifest = read_profile_manifest('dsh', str(directory))
    assert manifest['dsh']['profile']['bundles'] == [PACKAGE]
    assert not (directory / store.JOURNAL).exists()


@pytest.mark.asyncio
async def test_failed_release_import_can_be_rolled_back_and_booted(profile, tmp_path):
    home, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path, broken=True)
    assert plugin_cli.run_plugin('python-test', ['upgrade', str(source)]) == 0
    with pytest.raises(Exception, match='bad release import'):
        await boot(home)
    assert plugin_cli.run_plugin('python-test', ['rollback', PACKAGE]) == 0
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'recovered') == 'Python echo: recovered'
    finally:
        await close(result)


@pytest.mark.parametrize('failure', ['syntax', 'api', 'identity', 'same-version', 'changed-installed', 'changed-history', 'references'])
def test_invalid_replacement_preserves_profile_and_source(profile, tmp_path, failure):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    path = source / 'package.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if failure == 'syntax':
        (source / 'python/echo/plugin.py').write_text('def broken(:\n', encoding='utf-8')
    elif failure == 'api':
        manifest['dsh']['python']['apiVersion'] = 99
    elif failure == 'identity':
        manifest['name'] = '@deepseek-ai/dsh-tools'
    elif failure == 'same-version':
        manifest['version'] = '0.1.0'
    elif failure == 'changed-installed':
        (installed(directory) / 'README.md').write_text('user changes', encoding='utf-8')
    elif failure == 'references':
        profile_path = directory / 'package.json'
        value = json.loads(profile_path.read_text(encoding='utf-8'))
        value['dependencies'][PACKAGE] = 'file:elsewhere'
        profile_path.write_text(json.dumps(value), encoding='utf-8')
    elif failure == 'changed-history':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
        plugin_cli.run_plugin('python-test', ['rollback', PACKAGE])
        archive = Path(versions.archive_path(str(directory), PACKAGE, record(directory)['history'][0]))
        (archive / 'README.md').write_text('user changes', encoding='utf-8')
    path.write_text(json.dumps(manifest), encoding='utf-8')
    before, files = (directory / 'package.json').read_bytes(), store.file_hashes(str(installed(directory)))
    with pytest.raises((ValueError, RuntimeError)):
        plugin_cli.run_plugin('python-test', ['rollback', PACKAGE] if failure == 'changed-history' else ['upgrade', str(source)])
    assert (directory / 'package.json').read_bytes() == before
    assert store.file_hashes(str(installed(directory))) == files
    assert not (directory / store.JOURNAL).exists()


def test_version_reuse_with_different_source_is_rejected(profile, tmp_path):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    first = source_version(tmp_path)
    plugin_cli.run_plugin('python-test', ['upgrade', str(first)])
    plugin_cli.run_plugin('python-test', ['rollback', PACKAGE])
    (first / 'README.md').write_text('different published files', encoding='utf-8')
    before = (directory / 'package.json').read_bytes()
    with pytest.raises(ValueError, match='different recorded'):
        plugin_cli.run_plugin('python-test', ['upgrade', str(first)])
    assert (directory / 'package.json').read_bytes() == before


@pytest.mark.parametrize('operation', ['upgrade', 'rollback'])
@pytest.mark.parametrize('point', ['old-move', 'new-move', 'profile-before', 'profile-after', 'archive-after'])
@pytest.mark.asyncio
async def test_actual_process_exit_recovers_old_or_committed_generation(profile, tmp_path, operation, point):
    home, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    if operation == 'rollback':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
    before = (directory / 'package.json').read_bytes()
    code = """
import os,sys
from dsh.boot import python_plugins as store, python_plugin_versions as versions
from dsh.boot.profile_boot import INSTALL_ANCHOR
real_replace, real_atomic = os.replace, store.atomic_bytes
directory, operation, point, argument = sys.argv[1:]
def move(src,dst):
    real_replace(src,dst)
    if point == 'old-move' and dst.endswith('-old'):
        os._exit(37)
    if point == 'new-move' and 'node_modules' in dst.replace('\\\\','/').split('/'):
        os._exit(37)
    if point == 'archive-after' and versions.HISTORY in dst:
        os._exit(37)
def atomic(path,data):
    if path == os.path.join(directory,'package.json'):
        if point == 'profile-before': os._exit(37)
        real_atomic(path,data)
        if point == 'profile-after': os._exit(37)
    else: real_atomic(path,data)
os.replace, store.atomic_bytes = move, atomic
if operation == 'upgrade': versions.upgrade(directory,argument,INSTALL_ANCHOR)
else: versions.rollback(directory,argument)
"""
    child = subprocess.run([sys.executable, '-c', code, str(directory), operation, point,
        str(source) if operation == 'upgrade' else PACKAGE], cwd=str(ROOT), capture_output=True)
    assert child.returncode == 37, child.stderr
    assert (directory / store.JOURNAL).is_file()
    committed = point in ('profile-after', 'archive-after')
    result = await boot(home)
    try:
        new = (operation == 'upgrade') == committed
        assert await echo(result['ctx'], 'recovered') == ('Version two: ' if new else 'Python echo: ') + 'recovered'
        assert record(directory)['version'] == ('0.2.0' if new else '0.1.0')
        if not committed:
            assert (directory / 'package.json').read_bytes() == before
        assert not (directory / store.JOURNAL).exists()
        assert versions.versions(str(directory), PACKAGE)['versions'][0]['version'] == record(directory)['version']
    finally:
        await close(result)


@pytest.mark.parametrize('operation', ['upgrade', 'rollback'])
def test_manifest_publication_failure_restores_old_files(profile, tmp_path, monkeypatch, operation):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    if operation == 'rollback':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
    before, files = (directory / 'package.json').read_bytes(), store.file_hashes(str(installed(directory)))
    real = store.atomic_bytes
    def fail(path, data):
        if path == str(directory / 'package.json'):
            raise OSError('injected publication failure')
        return real(path, data)
    monkeypatch.setattr(store, 'atomic_bytes', fail)
    with pytest.raises(OSError, match='publication failure'):
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)] if operation == 'upgrade' else ['rollback', PACKAGE])
    assert (directory / 'package.json').read_bytes() == before
    assert store.file_hashes(str(installed(directory))) == files
    assert not (directory / store.JOURNAL).exists()


def test_versions_cli_is_json_and_does_not_invoke_pnpm(profile, tmp_path, capsys):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    plugin_cli.run_plugin('python-test', ['upgrade', str(source_version(tmp_path))])
    capsys.readouterr()
    assert plugin_cli.run_plugin('python-test', ['versions', PACKAGE]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['name'] == PACKAGE
    assert [(r['version'], r['current']) for r in value['versions']] == [('0.2.0', True), ('0.1.0', False)]
    assert all(len(r['generation']) == 64 for r in value['versions'])


def test_missing_history_unmanaged_package_and_invalid_command_do_not_change_profile(profile):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    before = (directory / 'package.json').read_bytes()
    for args in (['rollback', PACKAGE], ['rollback', '@other/missing'], ['versions'], ['rollback', PACKAGE, 'missing']):
        with pytest.raises(ValueError):
            plugin_cli.run_plugin('python-test', args)
        assert (directory / 'package.json').read_bytes() == before


def test_upgrade_of_missing_profile_does_not_initialize_it(profile):
    home, _ = profile
    with pytest.raises(ValueError, match='existing profile'):
        plugin_cli.run_plugin('new-empty', ['upgrade', str(EXAMPLE)])
    assert not (home / 'profiles/new-empty/package.json').exists()


def test_real_cli_processes_upgrade_versions_and_rollback_with_empty_path(profile, tmp_path):
    _, directory = profile
    source = source_version(tmp_path)
    environment = dict(os.environ, PATH='')
    def cli(*args):
        child = subprocess.run([sys.executable, str(ROOT / 'dsh.py'), 'plugin', '--profile', 'python-test'] + list(args),
            cwd=str(ROOT), env=environment, capture_output=True, text=True, encoding='utf-8')
        assert child.returncode == 0, child.stderr
        return child.stdout
    cli('add', str(EXAMPLE))
    cli('upgrade', str(source))
    assert [r['version'] for r in json.loads(cli('versions', PACKAGE))['versions']] == ['0.2.0', '0.1.0']
    cli('rollback', PACKAGE)
    assert record(directory)['version'] == '0.1.0'
    cli('remove', PACKAGE)
    assert not installed(directory).exists()


@pytest.mark.parametrize('operation', ['upgrade', 'rollback'])
def test_file_in_use_rename_failure_recovers_old_version(profile, tmp_path, monkeypatch, operation):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    if operation == 'rollback':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
    before, files = (directory / 'package.json').read_bytes(), store.file_hashes(str(installed(directory)))
    real = os.replace
    failed = False
    def fail(src, dst):
        nonlocal failed
        if not failed and dst == str(installed(directory)):
            failed = True
            raise PermissionError('injected file in use')
        return real(src, dst)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(PermissionError, match='file in use'):
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)] if operation == 'upgrade' else ['rollback', PACKAGE])
    assert failed
    assert (directory / 'package.json').read_bytes() == before
    assert store.file_hashes(str(installed(directory))) == files
    assert not (directory / store.JOURNAL).exists()


@pytest.mark.parametrize('operation', ['upgrade', 'rollback'])
def test_external_profile_edit_during_prepare_is_preserved(profile, tmp_path, monkeypatch, operation):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    if operation == 'rollback':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
    files = store.file_hashes(str(installed(directory)))
    real = versions.read_profile_manifest
    def edit(bin_name, path):
        manifest = real(bin_name, path)
        (directory / 'package.json').write_text(json.dumps(dict(manifest, userEdit='preserve')), encoding='utf-8')
        return manifest
    monkeypatch.setattr(versions, 'read_profile_manifest', edit)
    with pytest.raises(RuntimeError, match='profile changed'):
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)] if operation == 'upgrade' else ['rollback', PACKAGE])
    assert read_profile_manifest('dsh', str(directory))['userEdit'] == 'preserve'
    assert store.file_hashes(str(installed(directory))) == files
    assert not (directory / store.JOURNAL).exists()


def test_modified_pending_transaction_is_retained_without_deleting_unknown_files(profile, tmp_path):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    code = """
import os,sys
from dsh.boot import python_plugins as store, python_plugin_versions as versions
from dsh.boot.profile_boot import INSTALL_ANCHOR
real = store.atomic_bytes
def interrupt(path,data):
    if path == os.path.join(sys.argv[1],'package.json'): os._exit(37)
    real(path,data)
store.atomic_bytes = interrupt
versions.upgrade(sys.argv[1],sys.argv[2],INSTALL_ANCHOR)
"""
    child = subprocess.run([sys.executable, '-c', code, str(directory), str(source)], cwd=str(ROOT), capture_output=True)
    assert child.returncode == 37, child.stderr
    target = installed(directory)
    (target / 'README.md').write_text('external edit after interrupted transaction', encoding='utf-8')
    with pytest.raises(RuntimeError, match='files changed'):
        store.recover(str(directory))
    assert (directory / store.JOURNAL).is_file()
    assert (target / 'README.md').read_text(encoding='utf-8') == 'external edit after interrupted transaction'
    journal = json.loads((directory / store.JOURNAL).read_text(encoding='utf-8'))
    backup = directory / store.STAGING / (journal['token'] + '-old')
    assert store.file_hashes(str(backup)) == journal['old']['files']


@pytest.mark.asyncio
async def test_host_lease_blocks_upgrade_until_async_unload_finishes(profile, tmp_path):
    home, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    result = await boot(home)
    entered, release = asyncio.Event(), asyncio.Event()
    async def cleanup():
        entered.set()
        await release.wait()
    result['ctx'].disposable(cleanup)
    closing = asyncio.create_task(close(result))
    await entered.wait()
    before = (directory / 'package.json').read_bytes()
    try:
        with pytest.raises(RuntimeError, match='profile is in use'):
            plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
        assert (directory / 'package.json').read_bytes() == before
    finally:
        release.set()
        await closing
    assert plugin_cli.run_plugin('python-test', ['upgrade', str(source)]) == 0
    assert record(directory)['version'] == '0.2.0'


def test_three_versions_preserve_history_and_package_removal_keeps_archived_sources(profile, tmp_path):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    plugin_cli.run_plugin('python-test', ['upgrade', str(source_version(tmp_path))])
    plugin_cli.run_plugin('python-test', ['upgrade', str(source_version(tmp_path, '0.3.0', 'Version three: '))])
    assert [r['version'] for r in versions.versions(str(directory), PACKAGE)['versions']] == ['0.3.0', '0.1.0', '0.2.0']
    plugin_cli.run_plugin('python-test', ['rollback', PACKAGE, '0.1.0'])
    assert [r['version'] for r in versions.versions(str(directory), PACKAGE)['versions']] == ['0.1.0', '0.2.0', '0.3.0']
    archives = [Path(versions.archive_path(str(directory), PACKAGE, r)) for r in record(directory)['history']]
    plugin_cli.run_plugin('python-test', ['remove', PACKAGE])
    assert not installed(directory).exists() and all(path.is_dir() for path in archives)


def test_upgrade_preserves_pnpm_forwarding_for_plain_packages(profile, monkeypatch):
    from dsh.boot.profile_lease import ProfileLease
    _, directory = profile
    called = []
    monkeypatch.setattr(plugin_cli.shutil, 'which', lambda _: 'pnpm')
    def pnpm(command, cwd):
        called.append(command)
        with pytest.raises(RuntimeError, match='profile is in use'):
            ProfileLease(cwd, exclusive=True)
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(plugin_cli.subprocess, 'run', pnpm)
    assert plugin_cli.run_plugin('python-test', ['upgrade', 'ordinary-package']) == 0
    assert called == [['pnpm', 'upgrade', 'ordinary-package']]


@pytest.mark.asyncio
async def test_real_web_profile_upgrade_and_rollback_execute_correct_source(profile, tmp_path, monkeypatch):
    home, _ = profile
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    plugin_cli.run_plugin('web', ['add', str(EXAMPLE)])
    for action, expected in ((None, 'Python echo: '), ('upgrade', 'Version two: '), ('rollback', 'Python echo: ')):
        if action == 'upgrade':
            plugin_cli.run_plugin('web', ['upgrade', str(source_version(tmp_path))])
        elif action == 'rollback':
            plugin_cli.run_plugin('web', ['rollback', PACKAGE])
        result = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))
        try:
            assert result['ctx'].get('webServer').port > 0
            assert result['ctx'].get('connection') is not None
            assert result['ctx'].get('typertGateway') is not None
            assert await echo(result['ctx'], 'web') == expected + 'web'
        finally:
            await close(result)
    plugin_cli.run_plugin('web', ['remove', PACKAGE])


@pytest.mark.parametrize('linked', ['history', 'staging'])
def test_snapshot_junctions_are_rejected_without_touching_link_target(profile, tmp_path, linked):
    if os.name != 'nt':
        pytest.skip('Windows junction behavior')
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    source = source_version(tmp_path)
    if linked == 'history':
        plugin_cli.run_plugin('python-test', ['upgrade', str(source)])
        snapshot = Path(versions.archive_path(str(directory), PACKAGE, record(directory)['history'][0]))
        held = tmp_path / 'held-snapshot'
        os.replace(str(snapshot), str(held))
        link = snapshot
    else:
        held = tmp_path / 'held-stage'
        held.mkdir()
        link = directory / store.STAGING
        link.rmdir()
    sentinel = held / 'user-file.txt'
    sentinel.write_text('preserve', encoding='utf-8')
    child = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(held)], capture_output=True)
    assert child.returncode == 0, child.stderr
    before = (directory / 'package.json').read_bytes()
    try:
        with pytest.raises(ValueError, match='link|root'):
            plugin_cli.run_plugin('python-test', ['rollback', PACKAGE] if linked == 'history' else ['upgrade', str(source)])
        assert (directory / 'package.json').read_bytes() == before
        assert sentinel.read_text(encoding='utf-8') == 'preserve'
    finally:
        # Remove only the junction itself, then restore the held snapshot.
        os.rmdir(str(link))
        if linked == 'history':
            os.replace(str(held), str(link))


def test_versions_refuses_an_unrecovered_transaction(profile):
    _, directory = profile
    plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
    journal = directory / store.JOURNAL
    journal.write_text('{}', encoding='utf-8')
    try:
        with pytest.raises(RuntimeError, match='pending plugin transaction'):
            plugin_cli.run_plugin('python-test', ['versions', PACKAGE])
        assert journal.read_text(encoding='utf-8') == '{}'
    finally:
        journal.unlink()
