import ctypes
from ctypes import wintypes
import os
import threading
import time

import pytest

from scripts import verify_release as gate


def hold(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x02000000, None)
    assert handle != wintypes.HANDLE(-1).value
    return kernel, handle


@pytest.mark.skipif(os.name != 'nt', reason='actual Win32 sharing ownership')
def test_actual_released_reader_allows_retention(tmp_path):
    source, target = tmp_path / 'owned', tmp_path / 'retained'
    source.mkdir()
    (source / 'raw.json').write_text('{"raw":true}', encoding='utf-8')
    kernel, handle = hold(source)
    try:
        with pytest.raises(PermissionError):
            os.rename(str(source), str(target))
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    released = []
    timer = threading.Timer(0.08, lambda: released.append(bool(kernel.CloseHandle(handle))))
    timer.start()
    try:
        gate.retain_regression_workspace(source, target)
    finally:
        timer.join()
    assert released == [True]
    assert not source.exists()
    assert (target / 'raw.json').read_text(encoding='utf-8') == '{"raw":true}'


@pytest.mark.skipif(os.name != 'nt', reason='actual Win32 sharing ownership')
def test_permanent_reader_preserves_raw_workspace(tmp_path):
    source, target = tmp_path / 'owned', tmp_path / 'retained'
    source.mkdir()
    raw = source / 'raw.json'
    raw.write_text('first raw observation', encoding='utf-8')
    kernel, handle = hold(source)
    started = time.monotonic()
    try:
        with pytest.raises(PermissionError) as error:
            gate.retain_regression_workspace(source, target, timeout=0.08)
        assert error.value.winerror in (5, 32, 33)
        assert time.monotonic() - started < 0.5
        assert raw.read_text(encoding='utf-8') == 'first raw observation'
        assert not target.exists()
    finally:
        assert kernel.CloseHandle(handle)


def test_collision_during_retry_never_overwrites_observation(tmp_path, monkeypatch):
    source, target = tmp_path / 'owned', tmp_path / 'retained'
    source.mkdir()
    (source / 'raw').write_text('owned', encoding='utf-8')
    first = PermissionError('first sharing denial')
    first.winerror = 5
    calls = []

    def collide(*args):
        calls.append(args)
        target.mkdir()
        (target / 'raw').write_text('foreign', encoding='utf-8')
        raise first

    monkeypatch.setattr(gate.os, 'rename', collide)
    with pytest.raises(PermissionError) as raised:
        gate.retain_regression_workspace(source, target)
    assert raised.value is first and len(calls) == 1
    assert (source / 'raw').read_text(encoding='utf-8') == 'owned'
    assert (target / 'raw').read_text(encoding='utf-8') == 'foreign'


def test_nonsharing_failure_is_immediate_and_exact(tmp_path, monkeypatch):
    source = tmp_path / 'owned'
    source.mkdir()
    first = PermissionError('actual permission denial')
    first.winerror = 87
    calls = []

    def deny(*args):
        calls.append(args)
        raise first

    monkeypatch.setattr(gate.os, 'rename', deny)
    with pytest.raises(PermissionError) as raised:
        gate.retain_regression_workspace(source, tmp_path / 'retained')
    assert raised.value is first and len(calls) == 1


def test_deadline_preserves_first_denial(tmp_path, monkeypatch):
    source = tmp_path / 'owned'
    source.mkdir()
    errors = []

    def deny(*args):
        error = PermissionError('sharing denial ' + str(len(errors)))
        error.winerror = 32
        errors.append(error)
        raise error

    monkeypatch.setattr(gate.os, 'rename', deny)
    with pytest.raises(PermissionError) as raised:
        gate.retain_regression_workspace(source, tmp_path / 'retained', timeout=0.05)
    assert len(errors) > 1 and raised.value is errors[0]
    assert source.is_dir()


@pytest.mark.parametrize('exitstatus', [0, 1])
def test_retention_guard_preserves_primary_regression_outcome(tmp_path, monkeypatch, exitstatus):
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    output = tmp_path / '.goose/out/result'
    output.mkdir(parents=True)
    monkeypatch.setattr(gate, 'run', lambda *args, **kwargs: exitstatus)
    def reject(*args):
        raise RuntimeError('workspace identity changed')
    monkeypatch.setattr(gate, 'retain_regression_workspace', reject)
    with pytest.raises(RuntimeError, match='pytest failed' if exitstatus else 'workspace identity changed'):
        gate.run_python_regression('python', output, {})
    assert 'workspace identity changed' in (output / 'pytest-retention-failure.json').read_text(encoding='utf-8')
