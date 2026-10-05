import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.session_diagnostic_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import diagnostic_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('accepted', 'error-name', 'error-text', 'lossless-first', 'restore-negative-zero',
    'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('session-diagnostic-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_diagnostic_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_public_session_admission_diagnostics_match_source(name, actual_pair):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', DAMAGES)
def test_session_diagnostic_receipt_requires_exact_errors_and_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    if damage == 'accepted':
        runtime['rows'][0]['accepted'] = not runtime['rows'][0]['accepted']
    elif damage == 'error-name':
        runtime['rows'][0]['error']['name'] = 'ValueError'
    elif damage == 'error-text':
        next(row for row in runtime['rows'] if row['name'] == 'create/version/empty-array')['error']['message'] = 'session header version must be 0, got []'
    elif damage == 'lossless-first':
        next(row for row in runtime['rows'] if row['name'] == 'create/version/nan')['error']['message'] = 'session header version must be 0, got NaN'
    elif damage == 'restore-negative-zero':
        next(row for row in runtime['rows'] if row['name'] == 'restore/version/negative-zero')['accepted'] = False
    elif damage == 'missing-case':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'root':
        runtime['root'] = str(tmp_path)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/cordis/utils.py']
    else:
        modules['dsh/cordis/utils.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_session_diagnostic_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/core/session/src/types.ts']
    else:
        source['inputs']['reference/packages/core/session/src/types.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_diagnostic_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both Session diagnostic'):
        diagnostic_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
