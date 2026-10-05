import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import jsonl_sharing_oracle as oracle
from scripts.verify_portable import sharing_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('header', 'event', 'raw', 'filename', 'tail', 'duplicate', 'order',
    'root', 'python', 'executable', 'module', 'bytes')


def damage_observations(runtime, damage):
    observed = runtime['rows'][0]['observed']
    if damage == 'header':
        observed['listed'][0]['id'] = 'foreign'
    elif damage == 'event':
        observed['inspected']['events'][0]['time'] += 1
    elif damage == 'raw':
        observed['raw']['content'] += 'foreign'
    elif damage == 'filename':
        observed['raw']['filename'] = 'foreign'
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'order':
        runtime['rows'].reverse()
    else:
        raise ValueError('Unknown observation damage')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('jsonl-sharing-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/jsonl_sharing_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'matched' and report['cases'] == 4
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_jsonl_shared_readers_match(actual_pair, name):
    source, native = actual_pair
    assert next(row for row in source['rows'] if row['name'] == name) == next(row for row in native['rows'] if row['name'] == name)
    oracle.validate_runtime(native, ROOT, oracle.identity(source), native['modules'])


@pytest.mark.parametrize('damage', DAMAGES)
def test_jsonl_sharing_receipt_requires_complete_values_and_runtime(actual_pair, damage, monkeypatch):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    if damage == 'root':
        runtime['root'] = str(ROOT.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/session/file_io.py']
    elif damage == 'bytes':
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64)
    else:
        damage_observations(runtime, damage)
    with pytest.raises(ValueError):
        oracle.validate_runtime(runtime, ROOT, oracle.identity(source, check_files=False), original['modules'])


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_jsonl_sharing_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/jsonl_sharing.probe.spec.ts'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source)


@pytest.mark.skipif(os.name != 'nt', reason='Actual Win32 handle sharing control')
def test_real_exclusive_holder_remains_a_sharing_error(tmp_path):
    from dsh.session.file_io import open_shared_read
    from dsh.session.file_revision import _windows_api
    path = tmp_path / 'owned.jsonl'
    path.write_bytes(b'owned')
    api, _, _, _ = _windows_api()
    handle = api.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(OSError) as caught:
            open_shared_read(path)
        assert caught.value.winerror == 32
    finally:
        assert api.CloseHandle(handle)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_jsonl_sharing_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both JSONL sharing'):
        sharing_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')


@pytest.mark.skipif(os.name != 'nt', reason='Actual Win32 reader retirement control')
def test_reader_close_releases_actual_handle_for_exclusive_owner(tmp_path):
    from dsh.session.file_io import open_shared_read
    from dsh.session.file_revision import _windows_api
    path = tmp_path / 'owned.jsonl'
    path.write_bytes(b'owned')
    with open_shared_read(path) as stream:
        assert stream.read() == b'owned'
    api, _, _, _ = _windows_api()
    handle = api.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    assert api.CloseHandle(handle)


def test_missing_shared_reader_stays_file_not_found(tmp_path):
    from dsh.session.file_io import open_shared_read
    with pytest.raises(FileNotFoundError):
        open_shared_read(tmp_path / 'missing.jsonl')


@pytest.mark.skipif(os.name != 'nt', reason='Actual Win7 extended path reader control')
def test_shared_reader_handles_long_owned_paths(tmp_path):
    from dsh.session.file_io import open_shared_read
    directory = tmp_path / ('nested-' + 'x' * 100) / ('nested-' + 'y' * 100)
    directory.mkdir(parents=True)
    path = directory / 'owned.jsonl'
    assert len(str(path)) > 260
    path.write_bytes(b'owned')
    with open_shared_read(path) as stream:
        assert stream.read() == b'owned'
