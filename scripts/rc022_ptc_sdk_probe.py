"""Pair Python SDK declaration text with the unchanged rc022 renderer."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    scalars = [None, 42, {}, {'oneOf': []}, {'$ref': '#/x'},
        {'type': 'object', 'properties': 7}, {'type': 'string', 'enum': [1]},
        {'type': 'array'}, {'type': 'integer'}, {'type': 'number'},
        {'type': 'boolean', 'enum': [False, True]}, {'type': 'null'},
        {'type': 'integer', 'const': 2 ** 60}, {'type': 'number', 'const': 1e21},
        {'type': 'number', 'const': 1e-7},
        {'type': 'string', 'enum': ['a\x00b', 'ends\\', '"\n', '\ud800', 'a\u2028b', '\x85']},
        {'oneOf': [{'type': 'object', 'properties': {'x': {'type': 'string'}}}, {'type': 'null'}]}]
    obj = {'type': 'object', 'properties': {
        'path': {'type': 'string', 'description': '  Path\n\tto\ufefffile  '},
        'options': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'additionalProperties': False},
        'values': {'type': 'array', 'items': {'oneOf': [{'type': 'number'}, {'type': 'null'}]}}},
        'required': ['path'], 'additionalProperties': False}
    def tool(name, parameters=obj, output=obj, description='Read "file" \\\n\x00\x85\ud800'):
        return dict(name=name, description=description, parameters=parameters, output=output)
    sets = [[], [tool('read')], [tool('my-tool'), tool('class'), tool('_x'), tool('__class__')],
        [tool(name) for name in ('z', 'a_b', 'a-b', 'a b', 'a-b2', 'match', 'case', 'type', '路径')],
        [tool('numeric', {'type': 'object', 'properties': {'10': {}, '2': {}}})]]
    for field in ('class', '__token', 'ﬁeld', 'a-b', '__debug__', '路径', 'match', '__doc__'):
        sets.append([tool('field', {'type': 'object', 'properties': {field: {'type': 'string'}}})])
    sets.extend([[tool('empty', {'type': 'object', 'additionalProperties': False})],
        [tool('open', {'type': 'object'})], [tool('hostile', {'type': 'string', 'pattern': 'x'})],
        [tool('ga', {'type': 'object', 'properties': {'가': {'type': 'object', 'properties': {'ᆨ': {'type': 'object', 'additionalProperties': False}}}}})]])
    deep = {'type': 'string'}
    for _ in range(60):
        deep = {'type': 'array', 'items': deep}
    scalars.append(deep)
    sets.append([tool('deep', output=deep)])
    long = {'type': 'object', 'additionalProperties': False}
    for _ in range(90):
        long = {'type': 'object', 'properties': {'very_long_field_name': long}}
    sets.append([tool('long', parameters=long)])
    sets.append([tool('supplementary', output={'type': 'object', 'properties': {'𐐀' * 100: long}})])
    return dict(scalars=scalars, sets=sets)


async def observe():
    from dsh.core.ptc_sdk import json_schema_to_py, render_tools_sdk_py
    data = cases()
    rows = [dict(kind='scalar', value=json_schema_to_py(schema)) for schema in data['scalars']]
    for schemas in data['sets']:
        text = render_tools_sdk_py(schemas)
        code = text.split('```python\n', 1)[1].rsplit('\n```', 1)[0]
        compile(code, '<PTC SDK>', 'exec')
        rows.append(dict(kind='sdk', value=text))
    return rows


def prepare(output):
    path = output / 'cases.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_sdk.mts', scope='Python SDK text: validated schema projection, canonical outputs, ordered TypedDict declarations, exact escapes, exotic names, collisions and bounded deep schemas. Unicode table version skew is a separate Python 3.8 overlay check.',
        extra_inputs=[Path(__file__).resolve(), ROOT/'dsh/core/ptc_sdk.py', ROOT/'dsh/core/json_schema.py'], prepare=prepare)
