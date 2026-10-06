import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import llm_config_oracle as oracle
from scripts.canonical_llm_values import observation_digest as value_digest
from scripts.verify_portable import llm_config_receipts


ROOT = Path(__file__).resolve().parents[1]
VALUE_DAMAGES = ('config','boolean','max-null','reason-null','same','same-stop','input','after-change','error','code','hook','signal','trace','tail','duplicate','order','type','unknown')
RUNTIME_DAMAGES = ('root','python','executable','module','bytes','group-missing','group-rows','group-root','group-executable','group-module')


def damage_observations(runtime, damage):
    rows = runtime['rows']
    def selected(name):
        return next(row for row in rows if row['name'] == name)
    if damage == 'config':
        selected('query/plain')['observed']['result']['model'] = 'foreign'
    elif damage == 'boolean':
        selected('nullable/resolveCallConfig/bool-default')['observed']['input']['reasoningEffort'] = 1
    elif damage == 'max-null':
        selected('nullable/prepareCall/null-max')['observed']['result']['config']['maxTokens'] = 0
    elif damage == 'reason-null':
        selected('nullable/resolveCallConfig/null-no-default')['observed']['result']['reasoningEffort'] = False
    elif damage == 'same':
        selected('query/plain')['observed']['same'] = False
    elif damage == 'same-stop':
        selected('query/plain')['observed']['sameStop'] = False
    elif damage == 'input':
        selected('query/plain')['observed']['input']['extra']['value'] = 2
    elif damage == 'after-change':
        selected('query/plain')['observed']['inputAfterResultChange']['model'] = 'foreign'
    elif damage == 'error':
        selected('query/unsupported')['observed']['error']['message'] = 'foreign error'
    elif damage == 'code':
        selected('query/unsupported')['observed']['error']['code'] = 'FOREIGN_ERROR'
    elif damage == 'hook':
        selected('query/custom-prepare')['trace'][0]['kind'] = 'prepare'
    elif damage == 'signal':
        selected('query/plain')['trace'][0]['signalSame'] = False
    elif damage == 'trace':
        selected('query/defaults')['trace'].append(copy.deepcopy(selected('query/defaults')['trace'][0]))
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    elif damage == 'type':
        rows[0]['name'] = 7
    elif damage == 'unknown':
        selected('query/plain')['observed']['foreign'] = True
    else:
        raise ValueError('Unknown LLM config observation damage')
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
    output = tmp_path_factory.mktemp('llm-config-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_config_oracle.py'), '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'matched' and report['cases'] == 26
    return json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')), json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_llm_config_match(actual_pair, name):
    source, native = actual_pair
    source_row = next(row for row in source['rows'] if row['name'] == name)
    native_row = next(row for row in native['rows'] if row['name'] == name)
    assert value_digest([source_row], side='source') == value_digest([native_row], side='native')
    oracle.validate_runtime(native, ROOT, oracle.identity(source), native['modules'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES + RUNTIME_DAMAGES)
def test_llm_config_requires_complete_values_and_runtime(actual_pair, damage, monkeypatch):
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
        del runtime['groups']['query']
    elif damage == 'group-rows':
        runtime['groups']['query']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['query']['root'] = str(ROOT.parent)
    elif damage == 'group-executable':
        runtime['groups']['query']['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['query']['modules']['dsh/llm/call_config.py']
    else:
        damage_observations(runtime, damage)
    with pytest.raises(ValueError):
        oracle.validate_runtime(runtime, ROOT, oracle.identity(source, check_files=False), original['modules'])


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_llm_config_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/llm_config_query.probe.spec.ts'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source)

@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_llm_config_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both LLM config'):
        llm_config_receipts(str(tmp_path / 'source.json') if side == 'source' else None, str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
