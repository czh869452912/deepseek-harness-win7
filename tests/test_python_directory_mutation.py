import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading

import pytest

from apps.cli import plugin as plugin_cli
from dsh.boot import python_directory_mutation as mutation, python_plugins as store
from test_python_plugin_distribution import profile, boot, close, echo, EXAMPLE, PACKAGE
from test_python_plugin_versions import source_version


def hold(path):
    kernel = mutation._windows_api()
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x02000000, None)
    assert handle != wintypes.HANDLE(-1).value
    return kernel, handle


@pytest.mark.asyncio
@pytest.mark.parametrize('location', ['directory', 'file'])
@pytest.mark.parametrize('operation', ['add', 'upgrade', 'rollback'])
async def test_actual_package_publication_waits_for_released_sharing_owner(profile, tmp_path, monkeypatch, location, operation):
    home, directory = profile
    if operation != 'add':
        assert plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)]) == 0
    source = source_version(tmp_path) if operation != 'add' else EXAMPLE
    if operation == 'rollback':
        assert plugin_cli.run_plugin('python-test', ['upgrade', str(source)]) == 0
    original = store.replace_directory
    observations = []

    def publish(source_path, destination):
        if observations:
            return original(source_path, destination)
        held = Path(source_path) if location == 'directory' else Path(source_path) / 'package.json'
        kernel, handle = hold(held)
        try:
            with pytest.raises(PermissionError):
                os.replace(source_path, source_path + '-blocked-probe')
            observations.append(location)
            released = []

            def release():
                released.append(bool(kernel.CloseHandle(handle)))

            timer = threading.Timer(0.08, release)
            timer.start()
            try:
                original(source_path, destination)
            finally:
                timer.join()
            assert released == [True]
        except BaseException:
            if not observations:
                kernel.CloseHandle(handle)
            raise

    monkeypatch.setattr(store, 'replace_directory', publish)
    argument = PACKAGE if operation == 'rollback' else str(source)
    assert plugin_cli.run_plugin('python-test', [operation, argument]) == 0
    assert observations == [location]
    assert not (directory / store.JOURNAL).exists()
    result = await boot(home)
    try:
        assert await echo(result['ctx'], 'ready') == ('Version two: ' if operation == 'upgrade' else 'Python echo: ') + 'ready'
    finally:
        await close(result)


@pytest.mark.parametrize('location', ['directory', 'file'])
def test_permanent_directory_holder_preserves_complete_pending_transaction(profile, monkeypatch, location):
    _, directory = profile
    before = (directory / 'package.json').read_bytes()
    original = store.replace_directory
    handles = []

    def blocked(source, destination):
        handles.append(hold(source if location == 'directory' else os.path.join(source, 'package.json')))
        original(source, destination)

    monkeypatch.setattr(store, 'replace_directory', blocked)
    try:
        with pytest.raises(PermissionError) as raised:
            plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)])
        assert raised.value.winerror == 32
        assert (directory / 'package.json').read_bytes() == before
        journal = json.loads((directory / store.JOURNAL).read_text(encoding='utf-8'))
        stage = directory / store.STAGING / journal['token']
        assert store.file_hashes(str(stage)) == journal['files']
        assert not (directory / 'node_modules' / PACKAGE).exists()
    finally:
        for kernel, handle in handles:
            assert kernel.CloseHandle(handle)
    store.recover(str(directory))
    assert not (directory / store.JOURNAL).exists()
    assert not stage.exists()


def test_nonsharing_directory_publication_error_is_immediate_and_exact(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    error = PermissionError('unrelated permission error')
    error.winerror = 87
    calls = []

    def fail(source, destination):
        calls.append((source, destination))
        raise error

    monkeypatch.setattr(mutation.os, 'replace', fail)
    with pytest.raises(PermissionError) as raised:
        mutation.replace_directory(str(source), str(tmp_path / 'destination'))
    assert raised.value is error
    assert len(calls) == 1


def test_directory_publication_collision_preserves_both_owned_and_foreign_data(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir()
    target.mkdir()
    (source / 'data').write_text('owned', encoding='utf-8')
    (target / 'data').write_text('foreign', encoding='utf-8')
    with pytest.raises(PermissionError):
        mutation.replace_directory(str(source), str(target))
    assert (source / 'data').read_text(encoding='utf-8') == 'owned'
    assert (target / 'data').read_text(encoding='utf-8') == 'foreign'
