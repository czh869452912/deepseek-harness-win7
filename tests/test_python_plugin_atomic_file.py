"""Atomic native installer commit through actual Windows read-handle contention."""
import ctypes
from ctypes import wintypes
import os
import threading

import pytest

from dsh.boot import python_plugins


@pytest.mark.skipif(os.name != 'nt', reason='Windows share modes')
def test_atomic_install_commit_waits_for_real_non_delete_reader(tmp_path, monkeypatch):
    target = tmp_path / 'package.json'
    target.write_bytes(b'original-complete-manifest')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    contended = threading.Event()
    closed = []

    def release():
        if contended.wait(3):
            closed.append(bool(kernel.CloseHandle(handle)))

    thread = threading.Thread(target=release)
    thread.start()
    original = os.replace
    failures = []

    def replace(source, destination):
        try:
            return original(source, destination)
        except PermissionError as error:
            failures.append(error.winerror)
            assert target.read_bytes() == b'original-complete-manifest'
            contended.set()
            raise

    monkeypatch.setattr(python_plugins.os, 'replace', replace)
    try:
        python_plugins.atomic_bytes(str(target), b'new-complete-manifest')
    finally:
        contended.set()
        thread.join(4)
        if not closed:
            kernel.CloseHandle(handle)
    assert not thread.is_alive() and closed == [True]
    assert failures and all(code in (5, 32, 33) for code in failures)
    assert target.read_bytes() == b'new-complete-manifest'
    assert not list(tmp_path.glob('.dsh-write-*'))


def test_terminal_commit_error_preserves_first_outcome_and_original_bytes(tmp_path, monkeypatch):
    target = tmp_path / 'package.json'
    target.write_bytes(b'original')
    first = PermissionError('fixed access refusal')
    first.winerror = 5
    calls = []
    times = iter([10.0, 10.2, 11.1])
    monkeypatch.setattr(python_plugins.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(python_plugins.time, 'sleep', lambda _: None)

    def refused(*arguments):
        calls.append(arguments)
        if len(calls) == 1:
            raise first
        later = PermissionError('later access refusal')
        later.winerror = 5
        raise later

    monkeypatch.setattr(python_plugins.os, 'replace', refused)
    with pytest.raises(PermissionError) as observed:
        python_plugins.atomic_bytes(str(target), b'new')
    assert observed.value is first
    assert target.read_bytes() == b'original'
    assert not list(tmp_path.glob('.dsh-write-*'))


def test_unrelated_commit_failure_is_not_retried(tmp_path, monkeypatch):
    target = tmp_path / 'package.json'
    target.write_bytes(b'original')
    failure = OSError('unrelated failure')
    calls = []

    def refused(*arguments):
        calls.append(arguments)
        raise failure

    monkeypatch.setattr(python_plugins.os, 'replace', refused)
    with pytest.raises(OSError) as observed:
        python_plugins.atomic_bytes(str(target), b'new')
    assert observed.value is failure and len(calls) == 1
    assert target.read_bytes() == b'original'
