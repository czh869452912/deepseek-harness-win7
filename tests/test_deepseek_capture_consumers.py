import copy
import json
from pathlib import Path
import subprocess
import sys
import uuid
import re

import pytest

from scripts.deepseek_capture_oracle import canonical_rows, NAMES, identity, validate_runtime
from scripts.verify_portable import deepseek_capture_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('config-name', 'config-message', 'error-name', 'error-message', 'failure-message',
    'error-code', 'file-message', 'file-failure', 'file-quota', 'file-status', 'settings-model',
    'settings-provider', 'settings-retry', 'stream', 'serialization', 'usage', 'request-body',
    'accepted', 'origin', 'retry-failure', 'retry-delay', 'retry-policy', 'retry-number',
    'retry-split', 'retry-shared', 'retry-form', 'tail', 'duplicate', 'root', 'python',
    'executable', 'module', 'bytes')


def damage_observations(runtime, damage):
    rows = {row['id']: row for row in runtime['rows']}
    if damage in ('config-name', 'config-message'):
        rows['config-contradiction']['error'][damage.split('-')[1]] = 'foreign'
    elif damage in ('error-name', 'error-message', 'error-code'):
        rows['http-collision']['value']['error'][damage.split('-')[1]] = 'foreign'
    elif damage == 'failure-message':
        rows['http-collision']['value']['error']['failure']['message'] = 'foreign'
    elif damage.startswith('file-'):
        selected = next(row['value']['error'] for row in runtime['rows'] if row['id'].startswith('files-') and 'error' in row.get('value', {}))
        field = damage.split('-')[1]
        if field == 'failure':
            selected['failure']['message'] = 'foreign'
        else:
            selected[field] = 'foreign'
    elif damage.startswith('settings-'):
        selected = next(row['value'][0]['snapshot'] for row in runtime['rows'] if row['id'].startswith('settings-'))
        field = damage.split('-')[1]
        if field == 'model':
            selected['models'][0]['id'] = 'foreign'
        elif field == 'provider':
            selected['providers'].clear()
        else:
            selected['retry']['mode'] = 'foreign'
    elif damage in ('stream', 'serialization', 'usage'):
        fixture_kind = {'stream': 'stream', 'serialization': 'serialize', 'usage': 'usage'}[damage]
        fixtures = json.loads((ROOT / 'scripts/oracles/deepseek-fixtures.json').read_text(encoding='utf-8'))
        selected = next(fixture['id'] for fixture in fixtures if fixture['kind'] == fixture_kind)
        rows[selected]['value'] = 'foreign'
    elif damage == 'request-body':
        selected = next(row['value'] for row in runtime['rows'] if row['id'].startswith('http-') and row.get('value', {}).get('requests'))
        selected['requests'][0]['body']['model'] = 'foreign'
    elif damage == 'accepted':
        selected = next(row['value'] for row in runtime['rows'] if row['id'].startswith('http-') and row.get('value', {}).get('accepted'))
        selected['accepted'].append('foreign')
    elif damage == 'origin':
        rows['http-collision']['value']['originPort'] += 1
    elif damage.startswith('retry-'):
        events = rows['http-retry-server-recovery']['value']['retryEvents']
        selected = events[0]['data']
        field = damage.split('-')[1]
        if field == 'failure':
            selected['failure']['message'] = 'foreign'
        elif field == 'delay':
            selected['delayMs'] += 1
        elif field == 'policy':
            selected['policyKey'] = 'foreign'
        elif field == 'number':
            selected['retry'] += 1
        elif field == 'split':
            events[1]['data']['retryId'] = str(uuid.uuid4())
        elif field == 'shared':
            for event in rows['http-retry-exhausted']['value']['retryEvents']:
                event['data']['retryId'] = selected['retryId']
        else:
            selected['retryId'] = 'foreign'
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    else:
        raise ValueError('Unknown damage: ' + damage)


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('deepseek-capture-pair') / 'paired.json'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/deepseek_capture_oracle.py'), '--output', str(output)],
        cwd=str(ROOT), capture_output=True, timeout=180)
    (output.parent / 'runner.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_deepseek_capture_matches_source(name, actual_pair):
    source, native = actual_pair
    source_rows, _ = canonical_rows(source['rows'])
    native_rows, _ = canonical_rows(native['rows'])
    assert next(row for row in source_rows if row['id'] == name) == next(row for row in native_rows if row['id'] == name)


@pytest.mark.parametrize('damage', DAMAGES)
def test_deepseek_capture_receipt_requires_complete_rows_and_runtime(actual_pair, tmp_path, damage):
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
        del runtime['modules']['dsh/llm/deepseek_config.py']
    elif damage == 'bytes':
        modules['dsh/llm/deepseek_config.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    else:
        damage_observations(runtime, damage)
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules)


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_deepseek_capture_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/llm/llm-deepseek/src/serialize.ts']
    else:
        source['inputs']['reference/packages/llm/llm-deepseek/src/serialize.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


def test_actual_retry_ids_may_change_without_splitting_or_merging_chains(actual_pair):
    source, native = copy.deepcopy(actual_pair)
    aliases = {}
    for row in native['rows']:
        for event in row.get('value', {}).get('retryEvents', []) if isinstance(row.get('value'), dict) else []:
            original = event['data']['retryId']
            aliases.setdefault(original, str(uuid.uuid4()))
            event['data']['retryId'] = aliases[original]
    assert len(aliases) == 3
    validate_runtime(native, ROOT, identity(source), native['modules'])


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_deepseek_capture_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both DeepSeek capture'):
        deepseek_capture_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')


@pytest.mark.parametrize('mode', ('renamed', 'host', 'configured', 'bool'))
def test_actual_loopback_origin_keeps_listener_and_endpoint_relation(actual_pair, mode):
    source, runtime = copy.deepcopy(actual_pair)
    value = next(row for row in runtime['rows'] if row['id'] == 'http-success')['value']
    if mode == 'host':
        value['origin']['host'] = '0.0.0.0'
    elif mode == 'configured':
        value['origin']['baseURL'] += '/foreign'
    elif mode == 'bool':
        value['originPort'] = True
    else:
        original = value['origin']['baseURL']
        replacement = 'http://127.0.0.1:1'
        def visit(current):
            if isinstance(current, str):
                return re.sub(re.escape(original) + r'(?=$|[^0-9])', replacement, current)
            if isinstance(current, list):
                return [visit(item) for item in current]
            if isinstance(current, dict):
                return {name: visit(item) for name, item in current.items()}
            return current
        selected = visit(value)
        selected['originPort'] = selected['origin']['port'] = 1
        value.clear()
        value.update(selected)
    if mode == 'renamed':
        validate_runtime(runtime, ROOT, identity(source), runtime['modules'])
    else:
        with pytest.raises(ValueError):
            validate_runtime(runtime, ROOT, identity(source), runtime['modules'])
