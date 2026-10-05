import copy
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.core.session import Session
from scripts.session_restore_sign_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import restore_sign_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('accepted', 'signed-zero', 'input-value', 'safe-integer', 'error-text',
    'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('session-restore-sign-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_restore_sign_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_public_session_restore_numeric_values_match_source(name, actual_pair):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', DAMAGES)
def test_session_restore_sign_receipt_requires_numeric_identity_and_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    if damage == 'accepted':
        runtime['rows'][0]['accepted'] = False
    elif damage in ('signed-zero', 'input-value', 'safe-integer'):
        row = next(row for row in runtime['rows'] if row['name'] == 'createdAt/negative-zero')
        row[{'signed-zero': 'negativeZero', 'input-value': 'equalInput', 'safe-integer': 'safeInteger'}[damage]] = False
    elif damage == 'error-text':
        next(row for row in runtime['rows'] if row['name'] == 'version/fraction')['error']['message'] = 'wrong version'
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
        del runtime['modules']['dsh/core/session/types.py']
    else:
        modules['dsh/core/session/types.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_session_restore_sign_source_identity_is_required(actual_pair, damage):
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
def test_portable_restore_sign_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both Session restore sign'):
        restore_sign_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')


@pytest.mark.parametrize('field,attribute', [('version', 'version'), ('createdAt', 'created_at'),
    ('seedLength', 'seed_length'), ('delegationDepth', 'delegation_depth')])
@pytest.mark.parametrize('consumer', ['attribute', 'copy', 'deepcopy', 'export'])
def test_restored_header_signed_zero_survives_public_consumers(field, attribute, consumer):
    header = dict(id='s', version=0, createdAt=1)
    header[field] = -0.0
    session = Session.from_restore('s', [], header)
    if consumer == 'export':
        actual = session.header.to_dict()[field]
    else:
        selected = copy.copy(session.header) if consumer == 'copy' else copy.deepcopy(session.header) if consumer == 'deepcopy' else session.header
        actual = getattr(selected, attribute)
    assert actual == 0 and math.copysign(1, actual) < 0
    assert math.copysign(1, session.header[field]) < 0
