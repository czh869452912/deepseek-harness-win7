import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.boot import config_projection_current as carrier
from dsh.javascript.runtime import JavaScriptRuntimeError


class Node:
    def __init__(self, kind, meta=None, **fields):
        self.fields = dict(type=kind, meta=meta or {}, **fields)
        self.builder = None


def graph(*roots):
    heap, seen = [], {}

    def encode(value):
        if value is None or type(value) in (str, bool, int, float):
            return value
        if id(value) in seen:
            return dict(ref=seen[id(value)])
        index = len(heap)
        seen[id(value)] = index
        record = {}
        heap.append(record)
        if isinstance(value, Node):
            record.update(kind='schema', entries=[[k, encode(v)] for k, v in value.fields.items()])
            if value.builder is not None:
                record['builder'] = encode(value.builder)
        elif type(value) is list:
            record.update(kind='array', items=[encode(v) for v in value])
        elif type(value) is dict:
            record.update(kind='object', entries=[[k, encode(v)] for k, v in value.items()])
        else:
            raise TypeError(type(value))
        return dict(ref=index)

    result = dict(heap=heap, roots=[encode(root) for root in roots])
    return result


def observe(tmp_path, wires):
    rows = carrier.project_config_graphs(wires)
    (tmp_path / 'config-projection-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    return rows


def test_missing_defaults_nested_requirements_and_expressions(tmp_path):
    field = Node('string', {'required': True})
    root = Node('object', {'default': {}}, dict={'token': field})
    good, bad, nested = observe(tmp_path, [graph(Node('number', {'default': 3})),
        graph(Node('number', {'default': 'bad'})), graph(root)])
    assert good['results'][0]['value']['acceptsMissing'] is True
    assert bad['results'][0]['value']['acceptsMissing'] is False
    value = nested['results'][0]['value']
    assert value['acceptsMissing'] is False
    core = value['schema']['anyOf'][0]
    assert core['required'] == ['token']
    assert core['properties']['token']['anyOf'][1] == {'$ref': '#/$defs/loaderExpression'}


def test_recursive_graph_identity_and_lazy_builder_cache(tmp_path):
    root = Node('object')
    root.fields['dict'] = {'child': root}
    lazy = Node('lazy')
    lazy.builder = Node('string', {'required': True})
    cyclic, built = observe(tmp_path, [graph(root, root), graph(lazy, lazy)])
    for index, result in enumerate(cyclic['results']):
        value = result['value']
        assert list(value['definitions']) == ['graph%dRecursive0' % index]
        assert value['schema']['anyOf'][0] == {'$ref': '#/$defs/graph%dRecursive0' % index}
    assert built['builderCalls'] == [0]
    assert built['results'][0]['value']['schema'] == built['results'][1]['value']['schema']
    assert built['results'][0]['value']['acceptsMissing'] is False


def test_volatile_error_and_opaque_transform_never_executes(tmp_path):
    transform = Node('transform', inner=Node('number'))
    invalid = Node('array', inner=Node('string', {'volatile': True}))
    transformed, volatile = observe(tmp_path, [graph(transform), graph(invalid)])
    assert 'transform callback' in transformed['results'][0]['value']['limitations'][0]
    assert volatile['results'] == [{'error': 'config/inner: volatile fields require a fixed object path without an enclosing volatile field'}]


def test_cycle_annotation_is_not_silently_serialized(tmp_path):
    default = {}
    default['self'] = default
    result = observe(tmp_path, [graph(Node('string', {'default': default}))])[0]['results'][0]['value']
    assert result['acceptsMissing'] == 'unknown'
    assert result['limitations'] == ['config/default: annotation omitted: schema annotation contains a cycle']
    assert 'default' not in result['schema']


def test_private_graph_errors_and_builder_cycles_are_bounded(tmp_path):
    node = Node('lazy')
    node.builder = node
    malformed, cycle = observe(tmp_path, [dict(heap=[], roots=[{'ref': 5}]), graph(node)])
    assert malformed == {'error': 'invalid graph reference', 'builderCalls': []}
    assert cycle['results'] == [{'error': 'config: lazy cycle has no concrete schema'}]
    assert cycle['builderCalls'] == [0]


def test_resource_tampering_fails_before_worker_launch(tmp_path, monkeypatch):
    copied = tmp_path / 'carrier'
    shutil.copytree(str(carrier.RESOURCE_ROOT), str(copied))
    monkeypatch.setattr(carrier, 'RESOURCE_ROOT', copied)
    with (copied / 'projector.js').open('ab') as stream:
        stream.write(b'// changed')
    with pytest.raises(JavaScriptRuntimeError, match='resource bytes differ: projector.js'):
        carrier.project_config_graphs([])


def test_both_worker_architectures_produce_same_projection(tmp_path):
    root = Path(__file__).resolve().parents[1]
    executable = Path(os.environ.get('DSH_TEST_X86_PYTHON', ''))
    if not executable.is_file():
        pytest.skip('owned Python 3.8 x86 runtime not selected')
    wires = [graph(Node('number', {'default': 3})), graph(Node('const', value={'constructor': 3, 'a': None}))]
    path = tmp_path / 'graphs.json'
    path.write_text(json.dumps(wires), encoding='utf-8')
    script = ('import json,sys;sys.path.insert(0,sys.argv[2]);'
        'from dsh.boot.config_projection_current import project_config_graphs;'
        'print(json.dumps(project_config_graphs(json.load(open(sys.argv[1],encoding="utf-8")))))')
    completed = subprocess.run([str(executable.resolve()), '-c', script, str(path), str(root)], cwd=str(root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
    assert completed.returncode == 0, completed.stderr.decode('utf-8', errors='replace')
    assert json.loads(completed.stdout) == carrier.project_config_graphs(wires)


def test_manifest_records_exact_upstream_and_dependency_inputs():
    manifest = json.loads((carrier.RESOURCE_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['target_upstream'] == '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    for dependency in ['regexpp', 'ajv', 'fast-deep-equal', 'fast-uri', 'json-schema-traverse']:
        assert any(dependency in name for name in manifest['resources'])
    assert hashlib.sha256((carrier.RESOURCE_ROOT / 'manifest.json').read_bytes()).hexdigest() == carrier.MANIFEST_SHA256
