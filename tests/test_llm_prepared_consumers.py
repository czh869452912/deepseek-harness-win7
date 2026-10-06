import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import llm_prepared_oracle as oracle
from scripts.verify_portable import llm_prepared_receipts
from scripts.canonical_llm_values import observation_digest as value_digest


ROOT = Path(__file__).resolve().parents[1]
VALUE_DAMAGES = ('config','boolean','defaults','context','error','dispatch','trace','replay','signal','frozen','header','empty','message-form','message-split','tail','duplicate','order','type')
RUNTIME_DAMAGES = ('root','python','executable','module','bytes','group-missing','group-rows','group-root','group-executable','group-module')


def damage_observations(runtime, damage):
    rows = runtime['rows']
    def selected(name):
        return next(row for row in rows if row['name'] == name)
    if damage == 'config':
        selected('public/plain')['observed']['config']['model'] = 'foreign'
    elif damage == 'boolean':
        selected('equality/tokens-number-bool')['config']['maxTokens'] = True
    elif damage == 'defaults':
        selected('public/defaults')['observed']['adapterDefaults'].clear()
    elif damage == 'context':
        selected('public/plain')['observed']['context']['contextWindow'] += 1
    elif damage == 'error':
        selected('public/mismatch-model')['errors'][0]['message'] = 'foreign error'
    elif damage == 'dispatch':
        selected('public/plain')['requests'].clear()
    elif damage == 'trace':
        selected('public/plain')['trace'].reverse()
    elif damage == 'replay':
        selected('generation/shared-replay')['requests'][0]['values']['messages'][0]['source']['replayState']['opaque'] = 'foreign'
    elif damage == 'signal':
        selected('agent/signal')['trace'][1]['request']['signal']['same'] = False
    elif damage == 'frozen':
        selected('agent/defaults')['trace'][1]['frozen'] = False
    elif damage == 'header':
        event = next(event for event in selected('agent/request-overrides')['events'] if event['type'] == 'request/header')
        event['data']['header']['config']['maxTokens'] = 64
    elif damage == 'empty':
        event = next(event for event in selected('agent/defaults')['events'] if event['type'] == 'assistant/message')
        event['data']['message']['content'].append(dict(type='text',text=''))
    elif damage == 'message-form':
        selected('agent/defaults')['messages'][0]['id'] = 'foreign'
    elif damage == 'message-split':
        message = selected('agent/defaults')['requests'][0]['request']['messages'][0]
        message['id'] = 'c4bfbe82-3487-4fda-98dc-ec6cb743d97d'
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    elif damage == 'type':
        rows[0]['name'] = 7
    else:
        raise ValueError('Unknown LLM prepared observation damage')
    for group in oracle.GROUPS:
        child_rows = []
        for row in rows:
            if row['group'] == group:
                child = copy.deepcopy(row)
                del child['group']
                child['name'] = row['name'][len(group) + 1:] if isinstance(row['name'], str) else row['name']
                child_rows.append(child)
        runtime['groups'][group]['rows'] = child_rows


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('llm-prepared-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_prepared_oracle.py'), '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'matched' and report['cases'] == 108
    return json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')), json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_llm_prepared_match(actual_pair, name):
    source, native = actual_pair
    source_row = next(row for row in source['rows'] if row['name'] == name)
    native_row = next(row for row in native['rows'] if row['name'] == name)
    if source_row['group'] == 'agent':
        source_row, native_row = dict(source_row, group='retry'), dict(native_row, group='retry')
    assert value_digest([source_row], side='source') == value_digest([native_row], side='native')
    oracle.validate_runtime(native, ROOT, oracle.identity(source), native['modules'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES + RUNTIME_DAMAGES)
def test_llm_prepared_requires_complete_values_and_runtime(actual_pair, damage, monkeypatch):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    if damage == 'root':
        runtime['root'] = str(ROOT.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/llm/call_config.py']
    elif damage == 'bytes':
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64)
    elif damage == 'group-missing':
        del runtime['groups']['agent']
    elif damage == 'group-rows':
        runtime['groups']['agent']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['agent']['root'] = str(ROOT.parent)
    elif damage == 'group-executable':
        runtime['groups']['agent']['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['agent']['modules']['dsh/llm/call_config.py']
    else:
        damage_observations(runtime, damage)
    with pytest.raises(ValueError):
        oracle.validate_runtime(runtime, ROOT, oracle.identity(source, check_files=False), original['modules'])


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_llm_prepared_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/llm_prepared_public.probe.spec.ts'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source)


def test_llm_prepared_source_message_identity_retains_uuid_shape(actual_pair):
    source = copy.deepcopy(actual_pair[0])
    row = next(row for row in source['rows'] if row['name'] == 'agent/defaults')
    message = row['messages'][0]
    message['id'] = 'msg-12abcdef'
    with pytest.raises(ValueError):
        oracle.identity(source)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_llm_prepared_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both LLM prepared'):
        llm_prepared_receipts(str(tmp_path / 'source.json') if side == 'source' else None, str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
