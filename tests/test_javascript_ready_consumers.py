import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.javascript_ready_oracle import NAMES, identity, validate_runtime
from scripts.oracles.javascript_ready_python import observe
from scripts.verify_portable import ready_receipts


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('javascript-ready-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_ready_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.asyncio
@pytest.mark.parametrize('name', NAMES)
async def test_actual_held_ready_crosses_exit_before_admission(name, actual_pair):
    expected = next(row for row in actual_pair[0]['observations'] if row['name'] == name)
    actual = await observe(name == NAMES[1])
    assert actual == expected


@pytest.mark.parametrize('damage', ['outcome', 'cancel', 'late-event', 'child', 'exit', 'admitted',
    'first', 'disposed', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes',
    'asset-missing', 'asset-bytes'])
def test_ready_receipt_requires_complete_outcome_and_ownership(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules, assets = original['modules'].copy(), original['assets'].copy()
    row = runtime['observations'][0]
    if damage == 'outcome':
        row['result']['error'] = 'workflow worker failed: JavaScript worker already exited'
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
def test_ready_source_identity_is_required(actual_pair, damage):
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
def test_portable_ready_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both JavaScript Ready'):
        ready_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
