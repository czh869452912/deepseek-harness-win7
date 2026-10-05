import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.session_number_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import number_receipts
from dsh.core.session import Session


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('outcome', 'header-field', 'header-mutation', 'nested-mutation', 'input-mutation',
    'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('session-number-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_number_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_public_session_number_and_frozen_metadata_match_source(name, actual_pair):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', DAMAGES)
def test_session_number_receipt_requires_complete_metadata_and_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    if damage == 'outcome':
        runtime['rows'][0]['accepted'] = False
    elif damage == 'header-field':
        del next(row for row in runtime['rows'] if row['name'] == 'unknown-field')['header']['extra']
    elif damage in ('header-mutation', 'nested-mutation'):
        name = 'header-mutation' if damage == 'header-mutation' else 'nested-header-mutation'
        next(row for row in runtime['rows'] if row['name'] == name)['mutationAccepted'] = True
    elif damage == 'input-mutation':
        next(row for row in runtime['rows'] if row['name'] == 'unknown-field')['input']['extra']['nested'].append(3)
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
def test_session_number_source_identity_is_required(actual_pair, damage):
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
def test_portable_number_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both Session number'):
        number_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')


@pytest.mark.parametrize('action', ['copy', 'deepcopy', 'export', 'delete'])
def test_published_header_copies_remain_detached_and_immutable(action):
    supplied = dict(id='s', version=0, createdAt=1, extra=dict(nested=[1, 2]))
    original = Session.create('s', [], supplied).header
    header = copy.copy(original) if action == 'copy' else copy.deepcopy(original) if action == 'deepcopy' else original
    if action == 'export':
        exported = header.to_dict()
        exported['extra']['nested'].append(3)
    elif action == 'delete':
        with pytest.raises(TypeError):
            del header.created_at
    else:
        with pytest.raises(TypeError):
            header.created_at = 9
        with pytest.raises(TypeError):
            header['extra']['nested'].append(3)
    assert header.to_dict() == original.to_dict() == supplied
