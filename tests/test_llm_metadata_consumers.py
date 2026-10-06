import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import llm_metadata_oracle as oracle
from scripts.verify_portable import llm_metadata_receipts


ROOT = Path(__file__).resolve().parents[1]
VALUE_DAMAGES = ('model', 'context', 'reasoning', 'description', 'max-tokens', 'modalities', 'trace', 'tail', 'duplicate', 'order', 'type')
RUNTIME_DAMAGES = ('root', 'python', 'executable', 'module', 'bytes', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')


def damage_observations(runtime, damage):
    rows = runtime['rows']
    def result(name):
        return next(row for row in rows if row['name'] == 'catalog/' + name)['result']
    if damage == 'model':
        rows[0]['result'][0]['id'] = 'foreign'
    elif damage == 'context':
        result('context-valid-resolve')['context']['contextWindow'] += 1
    elif damage == 'reasoning':
        result('reasoning-valid-resolve')['reasoning']['efforts'][0]['name'] = 'foreign'
    elif damage == 'description':
        result('description-empty-resolve')['description'] = 'foreign'
    elif damage == 'max-tokens':
        result('defaultMaxTokens-valid-resolve')['defaultMaxTokens'] += 1
    elif damage == 'modalities':
        result('inputModalities-text-resolve')['inputModalities'].append('image')
    elif damage == 'trace':
        rows[0]['trace'][0]['provider'] = 'foreign'
    elif damage == 'type':
        rows[0]['result'][0]['id'] = 7
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    else:
        raise ValueError('Unknown LLM metadata observation damage')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('llm-metadata-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_metadata_oracle.py'), '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['status'] == 'matched' and report['cases'] == 137
    return json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')), json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', oracle.NAMES)
def test_actual_original_and_native_llm_metadata_match(actual_pair, name):
    source, native = actual_pair
    assert next(row for row in source['rows'] if row['name'] == name) == next(row for row in native['rows'] if row['name'] == name)
    oracle.validate_runtime(native, ROOT, oracle.identity(source), native['modules'])


@pytest.mark.parametrize('damage', VALUE_DAMAGES + RUNTIME_DAMAGES)
def test_llm_metadata_requires_complete_values_and_runtime(actual_pair, damage, monkeypatch):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    if damage == 'root':
        runtime['root'] = str(ROOT.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/llm/model_info.py']
    elif damage == 'bytes':
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64)
    elif damage == 'group-missing':
        del runtime['groups']['stream']
    elif damage == 'group-rows':
        runtime['groups']['stream']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['stream']['root'] = str(ROOT.parent)
    elif damage == 'group-executable':
        runtime['groups']['stream']['executable'] = str(ROOT / 'foreign/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['stream']['modules']['dsh/llm/model_info.py']
    else:
        damage_observations(runtime, damage)
    with pytest.raises(ValueError):
        oracle.validate_runtime(runtime, ROOT, oracle.identity(source, check_files=False), original['modules'])


@pytest.mark.parametrize('damage', ('pin', 'node', 'inputs', 'bytes'))
def test_llm_metadata_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'foreign'
    elif damage == 'inputs':
        source['inputs'].clear()
    else:
        source['inputs']['scripts/oracles/llm_metadata_catalog.probe.spec.ts'] = '0' * 64
    with pytest.raises(ValueError):
        oracle.identity(source)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_llm_metadata_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both LLM metadata'):
        llm_metadata_receipts(str(tmp_path / 'source.json') if side == 'source' else None, str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')
