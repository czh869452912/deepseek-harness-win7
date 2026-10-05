import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.persistence_read_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import read_receipts


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('persistence-read-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/persistence_read_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


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
        del row['error']
    elif damage == 'queue':
        next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/queued')['settledBeforeRelease'] = False
    elif damage == 'legacy':
        next(row for row in runtime['rows'] if row['name'] == 'sqlite/legacy-forward')['calls'][0]['signalForwarded'] = False
    elif damage == 'cancel-priority':
        next(row for row in runtime['rows'] if row['name'] == 'sqlite/aborted-failure')['error']['message'] = 'controlled read failure'
    elif damage == 'reason':
        row['reasonIdentity'] = False
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
        del runtime['modules']['dsh/session/coordinator.py']
    elif damage == 'module-bytes':
        modules['dsh/session/coordinator.py'] = '0' * 64
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
        del source['inputs']['reference/packages/session/session-persistence/src/coordinator.ts']
    else:
        source['inputs']['reference/packages/session/session-persistence/src/coordinator.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_read_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both persistence read'):
        read_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
