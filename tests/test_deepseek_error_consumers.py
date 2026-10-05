import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.deepseek_error_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import deepseek_error_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('error-name', 'error-message', 'failure-message', 'error-code', 'status', 'retry-after',
    'request-id', 'preview', 'surrogate', 'timer', 'fraction', 'chunk', 'request-body',
    'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes')


def damage_observations(runtime, damage):
    rows = {row['name']: row for row in runtime['rows']}
    if damage in ('error-name', 'error-message', 'error-code', 'status'):
        field = {'error-name': 'name', 'error-message': 'message', 'error-code': 'code', 'status': 'status'}[damage]
        rows['http-400']['error'][field] = 'foreign'
    elif damage == 'failure-message':
        rows['http-400']['error']['failure']['message'] = 'foreign'
    elif damage == 'retry-after':
        rows['rate-header']['error']['providerRetryAfterMs'] = 2001
    elif damage == 'request-id':
        rows['rate-header']['error']['requestId'] = 'foreign'
    elif damage in ('preview', 'surrogate', 'timer', 'fraction'):
        name = {'preview': 'invalid-data', 'surrogate': 'invalid-split-surrogate',
            'timer': 'idle-whole-float', 'fraction': 'idle-fraction'}[damage]
        rows[name]['error']['message'] = 'foreign'
        rows[name]['error']['failure']['message'] = 'foreign'
    elif damage == 'chunk':
        next(chunk for chunk in rows['success']['chunks'] if chunk['type'] == 'text-delta')['text'] = 'foreign'
    elif damage == 'request-body':
        rows['http-400']['requests'][0]['body']['model'] = 'foreign'
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    else:
        raise ValueError('Unknown observation damage: ' + damage)


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('deepseek-error-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/deepseek_error_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_deepseek_complete_http_failures_match_source(name, actual_pair):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', DAMAGES)
def test_deepseek_error_receipt_requires_complete_rows_and_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    if damage == 'root':
        runtime['root'] = str(tmp_path)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/llm/deepseek_wire.py']
    elif damage == 'bytes':
        modules['dsh/llm/deepseek_wire.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    else:
        damage_observations(runtime, damage)
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_deepseek_error_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/llm/llm-deepseek/src/translate.ts']
    else:
        source['inputs']['reference/packages/llm/llm-deepseek/src/translate.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('spelling', ['native-float', 'source-float', 'fraction'])
def test_actual_retry_hint_keeps_json_numeric_value(actual_pair, spelling):
    source, native = copy.deepcopy(actual_pair)
    selected = source if spelling == 'source-float' else native
    row = next(row for row in selected['rows'] if row['name'] == 'rate-header')
    value = 2000.5 if spelling == 'fraction' else 2000.0
    row['error']['providerRetryAfterMs'] = value
    row['error']['failure']['providerRetryAfterMs'] = value
    if spelling == 'fraction':
        with pytest.raises(ValueError):
            validate_runtime(native, ROOT, identity(source), native['modules'])
    else:
        validate_runtime(native, ROOT, identity(source), native['modules'])


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_deepseek_error_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both DeepSeek error'):
        deepseek_error_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
