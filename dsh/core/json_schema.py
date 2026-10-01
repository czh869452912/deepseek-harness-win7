"""The pinned tools package's enforced JSON Schema subset (Python 3.8)."""
import json
import math
import re

from dsh.cordis.utils import _js_own_enumerable_keys, js_to_string
from dsh.core.session.json import FrozenDict, FrozenList, UNDEFINED, is_json_value
from dsh.llm.error import HarnessError

TYPES = ('object', 'array', 'string', 'number', 'integer', 'boolean', 'null')
SIBLINGS = ('properties', 'required', 'additionalProperties', 'items', 'enum', 'const')
CONSTRAINTS = set(('type', 'oneOf') + SIBLINGS)
ANNOTATIONS = {'description', 'title', 'default', 'examples'}


class JsonSchemaError(HarnessError, TypeError):
    """Source error vocabulary; also catchable by historical Python TypeError consumers."""
    def __init__(self, violations):
        super().__init__('unsupported JSON schema: ' + '; '.join(violations), 'UNSUPPORTED_SCHEMA')
        self.name = 'JsonSchemaError'
        self.violations = violations


def is_json_schema_record(value):
    return type(value) in (dict, FrozenDict) and all(type(key) is str for key in value)


def is_plain_json_array(value):
    return type(value) in (list, FrozenList)


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and not (value == 0 and math.copysign(1, value) < 0)
    except OverflowError:
        return False


def _scalar(kind, value):
    if kind == 'string':
        return type(value) is str
    if kind == 'number':
        return _number(value)
    if kind == 'integer':
        return _number(value) and value == math.floor(value)
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'null':
        return value is None
    return False


def _same(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return float(left) == float(right)
    if type(left) is str and type(right) is str:
        return left.encode('utf-16-le', 'surrogatepass') == right.encode('utf-16-le', 'surrogatepass')
    return type(left) is type(right) and left == right


def _keys(record):
    return _js_own_enumerable_keys(record)


def _schema_issues(root, path):
    violations, seen = [], set()
    tasks = [('enter', root, path)]
    while tasks:
        kind, node, current = tasks.pop()
        if kind == 'leave':
            seen.remove(id(node))
            continue
        if kind == 'oneof-tail':
            for key in SIBLINGS:
                if key in node:
                    violations.append(current + '.' + key + ' is not supported beside oneOf')
            continue
        if kind == 'object-tail':
            properties = node.get('properties', UNDEFINED)
            if 'required' in node:
                required = node['required']
                if not is_plain_json_array(required) or any(type(key) is not str for key in required):
                    violations.append(current + '.required must be an array of strings')
                else:
                    declared = properties if is_json_schema_record(properties) else {}
                    for key in required:
                        if key not in declared:
                            violations.append('{}.required names "{}" which is not in properties'.format(current, key))
            if 'additionalProperties' in node and type(node['additionalProperties']) is not bool:
                violations.append(current + '.additionalProperties must be a boolean')
            continue
        if not is_json_schema_record(node):
            violations.append(current + ' must be a schema object')
            continue
        if id(node) in seen:
            violations.append(current + ' is circular')
            continue
        seen.add(id(node))
        tasks.append(('leave', node, current))
        for key in _keys(node):
            if key in CONSTRAINTS:
                continue
            if key in ANNOTATIONS:
                if not is_json_value(node[key]):
                    violations.append(current + '.' + key + ' annotation must be lossless JSON data')
            else:
                violations.append(current + '.' + key + ' is not a supported keyword (subset: type/oneOf/properties/required/additionalProperties/items/enum/const + annotations)')
        for key in ('description', 'title'):
            if key in node and type(node[key]) is not str:
                violations.append(current + '.' + key + ' must be a string')
        has_type, has_union = 'type' in node, 'oneOf' in node
        if has_type and has_union:
            violations.append(current + ' cannot declare both type and oneOf')
            continue
        if not has_type and not has_union:
            for key in SIBLINGS:
                if key in node:
                    violations.append(current + '.' + key + ' requires type or oneOf')
            continue
        if has_union:
            tasks.append(('oneof-tail', node, current))
            branches = node['oneOf']
            if not is_plain_json_array(branches) or len(branches) < 2:
                violations.append(current + '.oneOf must be an array of at least two schemas')
            else:
                for index in range(len(branches) - 1, -1, -1):
                    tasks.append(('enter', branches[index], '{}.oneOf[{}]'.format(current, index)))
            continue
        expected = node['type']
        if type(expected) is not str or expected not in TYPES:
            violations.append(current + ('.type must be a single type string (type arrays are not supported)'
                if isinstance(expected, list) else '.type must be one of ' + '/'.join(TYPES)))
            continue
        allowed = dict(properties=('object',), required=('object',), additionalProperties=('object',),
            items=('array',), enum=TYPES[2:], const=TYPES[2:])
        for key, types in allowed.items():
            if key in node and expected not in types:
                violations.append('{}.{} is not supported on type "{}"'.format(current, key, expected))
        if expected == 'object':
            tasks.append(('object-tail', node, current))
            if 'properties' in node:
                properties = node['properties']
                if not is_json_schema_record(properties):
                    violations.append(current + '.properties must be an object of schemas')
                else:
                    for key in reversed(_keys(properties)):
                        tasks.append(('enter', properties[key], current + '.properties.' + key))
        elif expected == 'array':
            if 'items' in node:
                tasks.append(('enter', node['items'], current + '.items'))
        else:
            values = node.get('enum', UNDEFINED)
            valid_enum = is_plain_json_array(values) and bool(values) and all(_scalar(expected, value) for value in values)
            if 'enum' in node and not valid_enum:
                violations.append('{}.enum must be a non-empty array of {} values'.format(current, expected))
            if 'const' in node:
                constant = node['const']
                if not _scalar(expected, constant):
                    violations.append('{}.const must be a {} value'.format(current, expected))
                elif valid_enum and not any(_same(constant, value) for value in values):
                    violations.append('{}.const must be one of {}.enum when both are declared'.format(current, current))
    return violations


def assert_supported_json_schema(schema, path='schema'):
    violations = _schema_issues(schema, path)
    if violations:
        raise JsonSchemaError(violations)


def assert_object_json_schema(schema):
    violations = _schema_issues(schema, 'schema')
    if not violations and schema.get('type') != 'object':
        violations.append('schema.type must be "object" (structured output is object-rooted)')
    if violations:
        raise JsonSchemaError(violations)


def _dump(value):
    if type(value) in (int, float):
        return js_to_string(value)
    if is_plain_json_array(value):
        return '[' + ','.join(_dump(item) for item in value) + ']'
    if type(value) is str:
        value = value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'surrogatepass')
        return re.sub('[\ud800-\udfff]', lambda match: '\\u{:04x}'.format(ord(match.group())),
            json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def validate_json_schema_value(schema, value, path='value'):
    def frame(node, candidate, current):
        return dict(node=node, value=candidate, path=current, catches=False,
            children=[], index=0, phase='start', kind=None, violations=[], tail=[], matches=0)
    frames, result = [frame(schema, value, path)], None
    def receive(issues):
        nonlocal result
        if not frames:
            result = issues
        elif frames[-1]['kind'] == 'union':
            if not issues:
                frames[-1]['matches'] += 1
        else:
            frames[-1]['violations'].extend(issues)
    def finish(issues):
        frames.pop()
        receive(issues)
    def lossless(current):
        return ['"{}" must be a lossless JSON value'.format(current or 'arguments')]
    def safe_json(candidate):
        try:
            return is_json_value(candidate)
        except Exception:
            return False
    while frames:
        item = frames[-1]
        node, candidate, current = item['node'], item['value'], item['path']
        label = current or 'arguments'
        try:
            if item['phase'] == 'children':
                if item['index'] < len(item['children']):
                    child = item['children'][item['index']]
                    item['index'] += 1
                    frames.append(frame(*child))
                    continue
                if item['kind'] == 'union':
                    count = item['matches']
                    finish([] if count == 1 else ['"{}" must match exactly one oneOf branch (matched {})'.format(label, count)])
                    continue
                item['violations'].extend(item['tail'])
                finish(item['violations'] if item['violations'] else [] if safe_json(candidate) else [
                    '"{}" must be {}'.format(label, 'a lossless JSON object' if item['kind'] == 'object' else 'a dense lossless JSON array')])
                continue
            expected = node.get('type', UNDEFINED)
            item['catches'] = expected is UNDEFINED or expected in TYPES
            branches = node.get('oneOf', UNDEFINED)
            if branches is not UNDEFINED:
                item.update(kind='union', children=[(branch, candidate, current) for branch in branches], phase='children')
                continue
            if expected is UNDEFINED:
                finish([] if safe_json(candidate) else lossless(current))
                continue
            if expected == 'object':
                if not is_json_schema_record(candidate):
                    finish(['"{}" must be an object'.format(label)])
                    continue
                properties = node.get('properties')
                properties = {} if properties is None or properties is UNDEFINED else properties
                required = node.get('required')
                required = [] if required is None or required is UNDEFINED else required
                property_path = lambda key: current + '.' + key if current else key
                issues = ['missing required property "{}"'.format(property_path(key))
                    for key in required if key not in candidate or candidate[key] is UNDEFINED]
                children = [(properties[key], candidate[key], property_path(key))
                    for key in _keys(properties) if key in candidate and candidate[key] is not UNDEFINED]
                tail = ['"{}" is not a declared property (additionalProperties: false)'.format(property_path(key))
                    for key in _keys(candidate) if key not in properties] if node.get('additionalProperties') is False else []
                item.update(kind='object', children=children, violations=issues, tail=tail, phase='children')
                continue
            if expected == 'array':
                if not isinstance(candidate, list):
                    finish(['"{}" must be an array'.format(label)])
                    continue
                items = node.get('items', UNDEFINED)
                children = [] if items is UNDEFINED else [(items, entry, '{}[{}]'.format(current, index)) for index, entry in enumerate(candidate)]
                item.update(kind='array', children=children, phase='children')
                continue
            if expected not in TYPES:
                raise RuntimeError('unreachable variant in JsonSchemaType: ' + _dump(expected))
            if not _scalar(expected, candidate):
                diagnostic = ('a finite JSON number' if expected == 'number' and type(candidate) in (int, float)
                    else 'null' if expected == 'null' else 'an integer' if expected == 'integer' else 'a ' + expected)
                finish(['"{}" must be {}'.format(label, diagnostic)])
            elif node.get('enum', UNDEFINED) is not UNDEFINED and not any(_same(candidate, entry) for entry in node['enum']):
                finish(['"{}" must be one of {}'.format(label, _dump(node['enum']))])
            elif 'const' in node and not _same(candidate, node['const']):
                finish(['"{}" must be {}'.format(label, _dump(node['const']))])
            else:
                finish([])
        except Exception:
            failed = frames.pop()
            while not failed['catches'] and frames:
                failed = frames.pop()
            if not failed['catches']:
                raise
            receive(lossless(failed['path']))
    return result if result is not None else lossless(path)


assertSupportedJsonSchema = assert_supported_json_schema
assertObjectJsonSchema = assert_object_json_schema
validateJsonSchemaValue = validate_json_schema_value
isJsonSchemaRecord = is_json_schema_record
isPlainJsonArray = is_plain_json_array
