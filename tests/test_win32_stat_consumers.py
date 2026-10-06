import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import win32_stat_oracle as oracle
from scripts.verify_portable import win32_stat_receipts


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows metadata provider contract')
VALUE_DAMAGES = ('stat-version', 'lstat-version', 'directory-size', 'change-time', 'file-identity',
    'missing', 'order', 'row', 'unknown', 'size-type')
RUNTIME_DAMAGES = ('module', 'bytes', 'root', 'python', 'executable', 'workspace')
HANDLE_DAMAGES = ('probe-count', 'handle-leak', 'failure-missing', 'failure-code', 'failure-close', 'failure-order', 'failure-type')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('win32-stat-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/win32_stat_oracle.py'), '--output', str(output)],
        cwd=str(ROOT), capture_output=True, timeout=200)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    summary = json.loads(output.read_text(encoding='utf-8'))
    assert summary['status'] == 'matched' and summary['cases'] == 7
    return json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')), json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_windows_stat_match(actual_pair, name):
    source, native = actual_pair
    assert next(row for row in source['rows'] if row['name'] == name) == next(row for row in native['rows'] if row['name'] == name)
    oracle.validate_runtime(native, ROOT, sys.executable, source, native['modules'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES + RUNTIME_DAMAGES + HANDLE_DAMAGES)
def test_windows_stat_requires_complete_values_and_handle_ownership(actual_pair, damage, monkeypatch):
    source, original = actual_pair
    native = copy.deepcopy(original)
    if damage == 'bytes':
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64)
    else:
        damage_runtime(native, damage, ROOT)
    with pytest.raises(ValueError):
        oracle.validate_runtime(native, ROOT, sys.executable, source, original['modules'])


def damage_runtime(native, damage, root):
    if damage == 'stat-version':
        native['rows'][0]['stat']['version'] += 'foreign'
    elif damage == 'lstat-version':
        native['rows'][0]['lstat']['version'] += 'foreign'
    elif damage == 'directory-size':
        native['rows'][4]['stat'].pop('size')
    elif damage == 'change-time':
        native['rows'][5]['raw']['ctimeNs'] = native['rows'][5]['raw']['mtimeNs']
    elif damage == 'file-identity':
        native['rows'][0]['raw']['ino'] = '0'
    elif damage == 'missing':
        native['rows'][-1]['stat'] = copy.deepcopy(native['rows'][0]['stat'])
    elif damage == 'order':
        native['rows'].reverse()
    elif damage == 'row':
        native['rows'].pop()
    elif damage == 'unknown':
        native['rows'][0]['foreign'] = True
    elif damage == 'size-type':
        native['rows'][1]['stat']['size'] = False
    elif damage == 'module':
        del native['modules']['dsh/fs/win32_stat.py']
    elif damage == 'root':
        native['root'] = str(root.parent)
    elif damage == 'python':
        native['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        native['executable'] = str(root / 'foreign/python.exe')
    elif damage == 'workspace':
        native['destination'] = str(root)
    elif damage == 'probe-count':
        native['handles']['successful_probes'] -= 1
    elif damage == 'handle-leak':
        native['handles']['final_handle_count'] += 1
    elif damage == 'failure-missing':
        native['handles']['failures'].pop()
    elif damage == 'failure-code':
        native['handles']['failures'][0]['winerror'] = 32
    elif damage == 'failure-close':
        native['handles']['failures'][0]['closed_handles'] = 0
    elif damage == 'failure-order':
        native['handles']['failures'].reverse()
    elif damage == 'failure-type':
        native['handles']['failures'][0]['closed_handles'] = True


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_windows_stat_requires_actual_source_identity(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/win32_stat_source.mts'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source, ROOT / 'reference')


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_windows_stat_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both Windows stat'):
        win32_stat_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
