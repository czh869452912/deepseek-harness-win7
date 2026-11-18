"""Historical persistence read controls; current storage has separate probes."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.persistence_read_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import read_receipts
from historical_domain_models import historical_identity, historical_pair


ROOT = Path(__file__).resolve().parents[1]
identity = historical_identity('persistence-read', identity)


@pytest.fixture(scope='module')
def actual_pair():
    return historical_pair('persistence-read')


@pytest.mark.parametrize('name', NAMES)
def test_actual_canonical_persistence_numeric_and_cancelled_reads_match_source(name, actual_pair):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', ['outcome', 'signal', 'after-read', 'queue', 'legacy', 'cancel-priority',
    'reason', 'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes', 'asset-bytes'])
def test_persistence_read_receipt_refuses_lost_semantics_and_foreign_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules, assets = original['modules'].copy(), original['assets'].copy()
    row = next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/abort/after-read')
    if damage == 'outcome':
        runtime['rows'][0]['accepted'] = False
    elif damage == 'signal':
        row['calls'][0]['signalForwarded'] = False
    elif damage == 'after-read':
        row['value']['events'][0]['time'] += 1
    elif damage == 'queue':
        next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/queued')['settledBeforeRelease'] = False
    elif damage == 'legacy':
        next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/read/whole')['value']['events'].clear()
    elif damage == 'cancel-priority':
        row['error'] = dict(name='Error',message='controlled read failure')
    elif damage == 'reason':
        next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/abort/before')['reasonIdentity'] = False
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
        del runtime['modules']['dsh/session/jsonl_handle.py']
    elif damage == 'module-bytes':
        modules['dsh/session/jsonl_handle.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    else:
        assets['dsh/session/bin/zstd/dsh_zstd.dll'] = '0' * 64
        runtime['assets'] = assets.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules, assets)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_persistence_read_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/session/session-persistence/src/handle.ts']
    else:
        source['inputs']['reference/packages/session/session-persistence/src/handle.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_read_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both persistence read'):
        read_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
