import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.office import runtime_inputs
from scripts import office_runtime_inputs
from scripts.rc022_office_runtime_probe import run_observer
from test_office_default_plugin import inventory


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job ownership')
def test_probe_timeout_joins_venv_redirector_and_descendant(tmp_path):
    import ctypes
    program = ('import subprocess,sys,time; '
               'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
               'print(child.pid,flush=True);time.sleep(60)')
    log_path = tmp_path / 'observer.log'
    with log_path.open('wb') as log, pytest.raises(subprocess.TimeoutExpired):
        run_observer([sys.executable, '-c', program], tmp_path, dict(os.environ), log, timeout=2)
    pid = int(log_path.read_text(encoding='utf-8').strip())
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    api.WaitForSingleObject.restype = ctypes.c_ulong
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            assert api.WaitForSingleObject(handle, 0) == 0
        finally:
            api.CloseHandle(handle)


def test_versioned_runtime_identities_match_approved_manifests():
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / 'scripts/office-runtime-inputs.json').read_text(encoding='utf-8'))['architectures']
    assert set(records) == set(runtime_inputs.MANIFESTS) == {'x64', 'x86'}
    for architecture, record in records.items():
        raw = (json.dumps(record['manifest'], indent=2) + '\n').encode('utf-8')
        assert hashlib.sha256(raw).hexdigest() == runtime_inputs.MANIFESTS[architecture] == record['manifest_sha256']
        resources = record['manifest']['resources']
        assert 'browser/CHROMIUM-LICENSE' in resources and 'browser/CHROMIUM-THIRD-PARTY-LICENSES.txt' in resources
        assert all(not name.endswith('interactive_ui_tests.exe') for name in resources)
        assert all('debug.log' not in name for name in resources)


def test_offline_copy_owns_only_approved_members_and_cannot_overwrite(tmp_path, monkeypatch):
    source = tmp_path / 'inputs/x64'
    source.mkdir(parents=True)
    inventory(source, monkeypatch)
    monkeypatch.setattr(office_runtime_inputs, 'MANIFESTS', runtime_inputs.MANIFESTS)
    (source / 'unowned.txt').write_bytes(b'not an input')
    selected = office_runtime_inputs.office_runtime_source(tmp_path, tmp_path / 'inputs')
    target = tmp_path / 'candidate'
    office_runtime_inputs.bundle_office_runtime(target, selected)
    installed = target / 'dsh/office/bin/x64'
    assert not (installed / 'unowned.txt').exists()
    assert runtime_inputs.verify_installed_runtime(installed, 'x64')['executable'] == str(installed / 'browser/chrome.exe')
    with pytest.raises(FileExistsError):
        office_runtime_inputs.bundle_office_runtime(target, selected)


def test_failed_copy_removes_its_owned_destination(tmp_path, monkeypatch):
    source = tmp_path / 'inputs/x64'
    source.mkdir(parents=True)
    inventory(source, monkeypatch)
    def failed(*args):
        raise OSError('copy failed')
    monkeypatch.setattr(office_runtime_inputs.shutil, 'copyfile', failed)
    with pytest.raises(OSError, match='copy failed'):
        office_runtime_inputs.bundle_office_runtime(tmp_path / 'candidate', source)
    assert not (tmp_path / 'candidate/dsh/office/bin/x64').exists()


def test_offline_selection_has_no_user_browser_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv('DSH_OFFICE_RUNTIME_INPUT_ROOT', raising=False)
    with pytest.raises(ValueError, match='missing or changed'):
        office_runtime_inputs.office_runtime_source(tmp_path)


def test_portable_cli_missing_office_input_preserves_existing_distribution(tmp_path):
    root = Path(__file__).resolve().parents[1]
    existing = tmp_path / 'dsh-win7-portable'
    existing.mkdir()
    (existing / 'keep.txt').write_bytes(b'previous distribution')
    archive = tmp_path / 'dsh-win7-portable-v0.1.5-rc.3-r2.zip'
    archive.write_bytes(b'previous archive')
    command = [sys.executable, str(root / 'scripts/build_portable.py'), '--office-runtime', str(tmp_path / 'missing-inputs'),
               '--output-dir', str(tmp_path), '--python-runtime', str(tmp_path / 'missing-python')]
    completed = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    assert completed.returncode != 0 and b'Pinned offline Office runtime input is missing or changed' in completed.stdout
    assert (existing / 'keep.txt').read_bytes() == b'previous distribution' and archive.read_bytes() == b'previous archive'
    assert not list(tmp_path.glob('.dsh-portable-candidate-*'))
