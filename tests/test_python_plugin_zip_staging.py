import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import zipfile

import pytest

from apps.cli import plugin as plugin_cli
from dsh.boot import python_plugins as installer
from test_python_plugin_distribution import profile, boot, close, echo, EXAMPLE, PACKAGE
from test_python_plugin_versions import source_version, zip_source


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['add', 'upgrade'])
@pytest.mark.skipif(sys.platform != 'win32', reason='actual Windows directory sharing contract')
async def test_wrapped_zip_needs_no_post_extraction_subroot_rename(profile, tmp_path, monkeypatch, operation):
    home, directory = profile
    if operation == 'upgrade':
        assert plugin_cli.run_plugin('python-test', ['add', str(EXAMPLE)]) == 0
        source = source_version(tmp_path)
    else:
        source = EXAMPLE
    archive = zip_source(source, tmp_path / 'wrapped.zip')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    original_copy = installer.copy_source
    original_validate = installer.validate_package
    held = []

    def release():
        for handle in handles:
            assert kernel.CloseHandle(handle)
        handles.clear()

    def copy(source, target):
        copied = original_copy(source, target)
        handle = kernel.CreateFileW(copied, 0x80000000, 3, None, 3, 0x02000000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append(handle)
        held.append(Path(copied))
        probe = copied + '-rename-probe'
        with pytest.raises(PermissionError):
            os.replace(copied, probe)
        return copied

    def validate(stage):
        if handles:
            assert held == [Path(stage)]
            assert (Path(stage) / 'package.json').is_file()
            assert not (Path(stage) / 'wrapped').exists()
            release()
        return original_validate(stage)

    monkeypatch.setattr(installer, 'copy_source', copy)
    monkeypatch.setattr(installer, 'validate_package', validate)
    try:
        assert plugin_cli.run_plugin('python-test', [operation, str(archive)]) == 0
    finally:
        release()
    result = await boot(home)
    try:
        expected = 'Version two: ready' if operation == 'upgrade' else 'Python echo: ready'
        assert await echo(result['ctx'], 'ready') == expected
        assert result['ctx'].get('tools') is not None
    finally:
        await close(result)
    assert not (directory / installer.JOURNAL).exists()
    assert (directory / 'node_modules' / PACKAGE / 'package.json').is_file()


@pytest.mark.parametrize('damage', ['traversal', 'collision', 'two-roots', 'root-file', 'oversize'])
def test_zip_preflight_rejects_invalid_container_before_writing(tmp_path, monkeypatch, damage):
    archive = tmp_path / 'invalid.zip'
    entries = [('wrapped/package.json', '{}')]
    if damage == 'traversal':
        entries.append(('wrapped/../escape.py', 'pass'))
    elif damage == 'collision':
        entries.append(('WRAPPED/PACKAGE.JSON', '{}'))
    elif damage == 'two-roots':
        entries.append(('foreign/file.py', 'pass'))
    elif damage == 'root-file':
        entries.append(('outside.py', 'pass'))
    else:
        monkeypatch.setattr(installer, 'MAX_BYTES', 1)
    with zipfile.ZipFile(str(archive), 'w', zipfile.ZIP_DEFLATED) as stream:
        for name, value in entries:
            stream.writestr(name, value)
    stage = tmp_path / 'stage'
    stage.mkdir()
    with pytest.raises(ValueError):
        installer.copy_source(str(archive), str(stage))
    assert list(stage.iterdir()) == []
