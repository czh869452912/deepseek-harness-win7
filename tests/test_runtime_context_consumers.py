import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.oracles.runtime_context_python import observe
from scripts.runtime_context_oracle import NAMES, canonical, identity, validate_runtime


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('runtime-context-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/runtime_context_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.asyncio
@pytest.mark.parametrize('action', NAMES)
async def test_model_tool_next_step_retains_complete_attributed_context(action, actual_pair):
    source, _ = actual_pair
    expected = next(row for row in source['observations'] if row['name'] == action)
    actual = await observe(action)
    assert canonical(actual) == canonical(expected)


@pytest.mark.parametrize('damage', ['attribution', 'second-step', 'clear', 'unchanged-duplicate',
    'identity-correlation', 'snapshot', 'missing-request', 'missing-case', 'duplicate', 'root', 'python',
    'executable', 'module', 'module-path', 'module-bytes'])
def test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    expected_digest = identity(source)
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    changed = runtime['observations'][0]
    if damage == 'attribution':
        message = next(message for message in changed['requests'][0]['messages']
            if message.get('source', {}).get('plugin') == '@deepseek-ai/dsh-system-prompt')
        message['source']['sections'] = []
    elif damage == 'second-step':
        changed['requests'][1]['messages'] = changed['requests'][0]['messages']
    elif damage == 'clear':
        cleared = runtime['observations'][1]
        cleared['requests'][1]['messages'] = cleared['requests'][0]['messages']
    elif damage == 'unchanged-duplicate':
        stable = runtime['observations'][2]
        stable['snapshots'].append(copy.deepcopy(stable['snapshots'][0]))
    elif damage == 'identity-correlation':
        changed['snapshots'][0]['id'] = '00000000-0000-4000-8000-000000000001'
    elif damage == 'snapshot':
        changed['snapshots'].pop()
    elif damage == 'missing-request':
        changed['requests'].pop()
    elif damage == 'missing-case':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(changed)
    elif damage == 'root':
        runtime['root'] = str(tmp_path)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/core/agent_loop.py']
    elif damage == 'module-path':
        modules['dsh/../foreign.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    else:
        modules['dsh/core/agent_loop.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, expected_digest, modules)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'guard-bytes'])
def test_runtime_context_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        source['inputs'].pop('reference/packages/core/agent-loop/src/agent.ts')
    else:
        source['inputs']['reference/packages/core/agent-loop/src/agent.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)
