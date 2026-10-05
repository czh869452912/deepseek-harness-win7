import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.javascript_initial_oracle import NAMES, identity, validate_runtime
from scripts.oracles.javascript_initial_python import observe
from scripts.oracles.javascript_initial_controls import observe as observe_pipe
from scripts.verify_portable import initial_receipts


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('javascript-initial-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_initial_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.asyncio
@pytest.mark.parametrize('name', NAMES)
async def test_actual_entry_exit_precedes_initial_write_failure(name, actual_pair):
    expected = next(row for row in actual_pair[0]['observations'] if row['name'] == name)
    actual = await observe(name == NAMES[1])
    assert actual == expected


@pytest.mark.parametrize('damage', ['outcome', 'cancel', 'late-event', 'child', 'exit', 'admitted', 'entry', 'emission',
    'first', 'disposed', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes',
    'asset-missing', 'asset-bytes'])
def test_initial_receipt_requires_complete_outcome_and_ownership(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules, assets = original['modules'].copy(), original['assets'].copy()
    row = runtime['observations'][0]
    if damage == 'outcome':
        row['result']['error'] = 'workflow worker failed: Connection lost'
    elif damage == 'cancel':
        runtime['observations'][1]['result']['stopReason'] = 'error'
    elif damage == 'late-event':
        row['events'].append(dict(type='phase', title='unreachable'))
    elif damage == 'child':
        row['requests'].append(dict(prompt='unreachable'))
    elif damage == 'exit':
        row['exitCode'] = 0
    elif damage == 'admitted':
        row['before']['readyAdmitted'] = True
    elif damage == 'entry':
        row['before']['entryBlocked'] = False
    elif damage == 'emission':
        row['before']['readyMessages'] = 1
    elif damage == 'first':
        row['firstResultRetained'] = False
    elif damage == 'disposed':
        row['goneAfterDispose'] = False
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][1] = copy.deepcopy(row)
    elif damage == 'root':
        runtime['root'] = str(tmp_path)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/javascript/runtime.py']
    elif damage == 'bytes':
        modules['dsh/javascript/runtime.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    elif damage == 'asset-missing':
        del runtime['assets']['dsh/javascript/bin/dsh_js_worker.exe']
    else:
        assets['dsh/javascript/workflow/source.js'] = '0' * 64
        runtime['assets'] = assets.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules, assets)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_initial_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/workflow/workflow-worker-thread/src/host.ts']
    else:
        source['inputs']['reference/packages/workflow/workflow-worker-thread/src/host.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_initial_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both JavaScript initial write'):
        initial_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')



@pytest.mark.asyncio
@pytest.mark.parametrize('error_type', [BrokenPipeError, ConnectionResetError])
async def test_live_initial_pipe_failure_keeps_original_identity(error_type):
    row = await observe_pipe(error_type, False)
    assert row['beforeCleanup']['exited'] is False
    assert row['beforeCleanup']['readyAdmitted'] is False
    assert row['result']['originalIdentity'] is True
    assert row['result']['workerFailureIdentity'] is False
    assert row['result']['code'] is None
    assert row['exitCode'] == 1 and row['closed'] is True
    assert row['ownedWorkers'] == row['ownedSpawns'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('error_type', [BrokenPipeError, ConnectionResetError])
async def test_exited_initial_pipe_failure_uses_recorded_physical_outcome(error_type):
    row = await observe_pipe(error_type, True)
    assert row['beforeCleanup']['exited'] is True
    assert row['beforeCleanup']['readyAdmitted'] is False
    assert row['result']['originalIdentity'] is False
    assert row['result']['workerFailureIdentity'] is True
    assert row['result']['originalCause'] is True
    assert row['result']['code'] == 'WORKER_EXIT'
    assert row['exitCode'] == 1 and row['closed'] is True
    assert row['ownedWorkers'] == row['ownedSpawns'] == 0
