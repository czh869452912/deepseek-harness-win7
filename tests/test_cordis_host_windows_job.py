"""Exercise the Win7 nested-Job branch with actual inherited kernel Jobs."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/oracles/cordis_host_job_python.py'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='actual Windows kernel Job handles')


def test_inherited_job_fallback_supports_rpc_and_native_timeout():
    process = subprocess.run([sys.executable, str(HELPER), 'normal'], cwd=str(ROOT),
        capture_output=True, encoding='utf-8', timeout=30,
        env=dict(os.environ, DSH_CORDIS_JOB_TEST_PATH=json.dumps(sys.path)),
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0, process.stdout + process.stderr
    observation = json.loads(process.stdout)
    assert observation['passed'] and observation['actualInheritedJob']
    assert observation['rpc'] and observation['nativeTimeout'] and observation['workerAndWatcherExited']


def test_inherited_job_watcher_kills_gil_blocked_worker_after_owner_death():
    process = subprocess.Popen([sys.executable, str(HELPER), 'parent-death'], cwd=str(ROOT),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, DSH_CORDIS_JOB_TEST_PATH=json.dumps(sys.path)),
        encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    lines = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
    reader.start()
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        observation = json.loads(lines.get(timeout=20))
        for key in ('worker', 'watchdog'):
            handle = api.OpenProcess(0x100000, False, observation[key])
            assert handle, ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        process.stdin.write('exit\n')
        process.stdin.flush()
        assert process.wait(timeout=5) == 0
        for handle in handles:
            assert api.WaitForSingleObject(handle, 5000) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for handle in handles:
            api.CloseHandle(handle)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
