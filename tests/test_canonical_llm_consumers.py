import copy
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from scripts import canonical_llm_oracle as oracle
from scripts.verify_portable import canonical_llm_receipts
from scripts.canonical_llm_values import observation_digest as value_digest


ROOT = Path(__file__).resolve().parents[1]
VALUE_DAMAGES = ('request', 'event', 'tool-id', 'message-form', 'message-split', 'message-cross-fixture',
    'retry-form', 'retry-split', 'retry-cross-fixture', 'tail', 'duplicate', 'order', 'type')
RUNTIME_DAMAGES = ('root', 'python', 'executable', 'module', 'bytes', 'group-missing', 'group-rows',
    'group-root', 'group-executable', 'group-module')


def replace_identity(value, original, replacement):
    if isinstance(value, str):
        return replacement if value == original else value
    if isinstance(value, list):
        return [replace_identity(item, original, replacement) for item in value]
    if isinstance(value, dict):
        return {key: replace_identity(item, original, replacement) for key, item in value.items()}
    return value


def damage_observations(runtime, damage):
    rows = runtime['rows']
    if damage == 'request':
        rows[0]['requests'][0]['body']['model'] = 'foreign'
    elif damage == 'event':
        rows[0]['events'][0]['data']['foreign'] = True
    elif damage == 'tool-id':
        selected = next(row for row in rows if row['name'] == 'retry/partial-tool')
        selected['requests'][-1]['body']['messages'][-1]['tool_call_id'] = 'foreign'
    elif damage.startswith('message-'):
        original = rows[0]['messages'][0]['id']
        if damage == 'message-form':
            rows[0]['messages'][0]['id'] = 'foreign'
        elif damage == 'message-split':
            rows[0]['messages'][0]['id'] = 'msg-' + str(uuid.uuid4())
        else:
            selected = rows[1]['messages'][0]['id']
            rows[1] = replace_identity(rows[1], selected, original)
    elif damage.startswith('retry-'):
        selected = next(event['data'] for event in rows[0]['events'] if event['type'] == 'llm/retry')
        if damage == 'retry-form':
            selected['retryId'] = 'foreign'
        elif damage == 'retry-split':
            selected['retryId'] = str(uuid.uuid4())
        else:
            owner = next(row for row in rows if row['name'] == 'retry/exhaust')
            next(event['data'] for event in owner['events'] if event['type'] == 'llm/retry')['retryId'] = selected['retryId']
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    elif damage == 'type':
        rows[0]['requests'][0]['body']['messages'][0]['content'] = False
    else:
        raise ValueError('Unknown canonical LLM observation damage')
    for group in oracle.GROUPS:
        child_rows = []
        for row in rows:
            if row['group'] == group:
                child = copy.deepcopy(row)
                del child['group']
                child['name'] = row['name'][len(group) + 1:]
                child_rows.append(child)
        runtime['groups'][group]['rows'] = child_rows


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('canonical-llm-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/canonical_llm_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'matched' and report['cases'] == 81
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_canonical_llm_match(actual_pair, name):
    source, native = actual_pair
    source_row = next(row for row in source['rows'] if row['name'] == name)
    native_row = next(row for row in native['rows'] if row['name'] == name)
    assert value_digest([source_row], side='source') == value_digest([native_row], side='native')
    oracle.validate_runtime(native, ROOT, oracle.identity(source), native['modules'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES + RUNTIME_DAMAGES)
def test_canonical_llm_requires_complete_values_identity_and_runtime(actual_pair, damage, monkeypatch):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    if damage in VALUE_DAMAGES:
        damage_observations(runtime, damage)
    elif damage == 'root':
        runtime['root'] = str(ROOT.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/llm/adapter_failure.py']
    elif damage == 'bytes':
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64)
    elif damage == 'group-missing':
        del runtime['groups']['iterator']
    elif damage == 'group-rows':
        runtime['groups']['iterator']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['iterator']['root'] = str(ROOT.parent)
    elif damage == 'group-executable':
        runtime['groups']['iterator']['executable'] = str(ROOT / 'foreign/python.exe')
    else:
        del runtime['groups']['iterator']['modules']['dsh/llm/llm_service.py']
    with pytest.raises(ValueError):
        oracle.validate_runtime(runtime, ROOT, oracle.identity(source, check_files=False), original['modules'])


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_canonical_llm_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/canonical-llm-fixtures.json'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source)


def test_literal_identity_marker_remains_a_literal_value():
    selected = str(uuid.uuid4())
    original = [dict(group='retry', name='fixture', messages=[dict(role='user', id=selected)], value=selected)]
    damaged = copy.deepcopy(original)
    damaged[0]['value'] = '__observed_message_0'
    assert value_digest(original) != value_digest(damaged)


def test_source_message_identity_retains_uuid_shape(actual_pair):
    source = copy.deepcopy(actual_pair[0])
    selected = source['rows'][0]['messages'][0]['id']
    source['rows'][0] = replace_identity(source['rows'][0], selected, 'msg-' + selected)
    with pytest.raises(ValueError):
        oracle.identity(source)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_canonical_llm_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both canonical LLM'):
        canonical_llm_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
