import copy
import json
import math
from pathlib import Path


ABSENT = object()
with (Path(__file__).with_name('schema_definitions.json')).open(encoding='utf-8') as stream:
    DEFINITIONS = json.load(stream)


class SchemaError(ValueError):
    def __init__(self, issues):
        self.name = 'ZodError'
        self.issues = issues
        self.message = json.dumps(issues, ensure_ascii=False, indent=2)
        super().__init__(self.message)


def _kind(value):
    if value is ABSENT:
        return 'undefined'
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'boolean'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    if type(value) in (int, float):
        return 'NaN' if math.isnan(value) else 'number'
    raise TypeError('MCP schemas only accept JSON values')


def _invalid(path, expected, value):
    return [(dict(expected=expected, code='invalid_type', path=list(path),
        message='Invalid input: expected %s, received %s' % (expected, _kind(value))), True)]


def _keys(value):
    numeric = [name for name in value if name.isascii() and name.isdigit() and str(int(name)) == name and int(name) < 4294967295]
    return sorted(numeric, key=int) + [name for name in value if name not in numeric]


def _parse(schema, value, path=()):
    kind = schema['type']
    if kind == 'optional':
        return (ABSENT, []) if value is ABSENT else _parse(schema['inner'], value, path)
    if kind == 'unknown':
        return (ABSENT if value is ABSENT else copy.deepcopy(value)), []
    if kind in ('string', 'boolean'):
        return (value, []) if _kind(value) == kind else (value, _invalid(path, kind, value))
    if kind == 'assert-object':
        if isinstance(value, (dict, list)):
            return copy.deepcopy(value), []
        return value, [(dict(code='custom', path=list(path), message='Invalid input'), True)]
    if kind == 'number':
        if type(value) not in (int, float) or not math.isfinite(value):
            return value, _invalid(path, 'number', value)
        safeint = schema.get('format') == 'safeint' or any(check.get('format') == 'safeint' for check in schema.get('checks', []))
        if safeint and int(value) != value:
            return value, [(dict(expected='int', format='safeint', code='invalid_type', path=list(path),
                message='Invalid input: expected int, received number'), True)]
        if safeint and abs(value) > 9007199254740991:
            positive = value > 0
            issue = dict(code='too_big' if positive else 'too_small')
            issue['maximum' if positive else 'minimum'] = 9007199254740991 if positive else -9007199254740991
            issue['note'] = 'Integers must be within the safe integer range.'
            issue.update(origin='int', inclusive=True, path=list(path), message='Too %s: expected int to be %s%s' % (
                'big' if positive else 'small', '<=' if positive else '>=', issue['maximum' if positive else 'minimum']))
            return value, [(issue, False)]
        return value, []
    if kind in ('literal', 'enum'):
        if any(type(value) is type(option) and value == option for option in schema['values']):
            return value, []
        options = [json.dumps(option, ensure_ascii=False, separators=(',', ':')) for option in schema['values']]
        message = 'Invalid input: expected ' + options[0] if len(options) == 1 else 'Invalid option: expected one of ' + '|'.join(options)
        return value, [(dict(code='invalid_value', values=schema['values'], path=list(path), message=message), True)]
    if kind == 'object':
        if not isinstance(value, dict):
            return value, _invalid(path, 'object', value)
        result, errors = {}, []
        for name, field in schema['shape'].items():
            parsed, issues = _parse(field, value.get(name, ABSENT), path + (name,))
            errors.extend(issues)
            if parsed is not ABSENT:
                result[name] = parsed
        catchall = schema.get('catchall')
        if catchall:
            extra = [name for name in _keys(value) if name not in schema['shape'] and name != '__proto__']
            if catchall['type'] == 'never' and extra:
                message = 'Unrecognized key%s: %s' % ('s' if len(extra) > 1 else '', ', '.join(json.dumps(name, ensure_ascii=False) for name in extra))
                errors.append((dict(code='unrecognized_keys', keys=extra, path=list(path), message=message), True))
            elif catchall['type'] != 'never':
                for name in extra:
                    parsed, issues = _parse(catchall, value[name], path + (name,))
                    result[name] = parsed
                    errors.extend(issues)
        return result, errors
    if kind == 'record':
        if not isinstance(value, dict):
            return value, _invalid(path, 'record', value)
        result, errors = {}, []
        for name in _keys(value):
            if name == '__proto__':
                continue
            parsed, issues = _parse(schema['value'], value[name], path + (name,))
            result[name] = parsed
            errors.extend(issues)
        return result, errors
    if kind == 'array':
        if not isinstance(value, list):
            return value, _invalid(path, 'array', value)
        result, errors = [], []
        for index, field in enumerate(value):
            parsed, issues = _parse(schema['element'], field, path + (index,))
            result.append(parsed)
            errors.extend(issues)
        return result, errors
    if kind == 'union':
        results = [_parse(option, value, path) for option in schema['options']]
        for parsed, errors in results:
            if not errors:
                return parsed, []
        continuing = [(parsed, errors) for parsed, errors in results if not any(aborted for issue, aborted in errors)]
        if len(continuing) == 1:
            return continuing[0]
        nested = [[dict(issue, path=issue['path'][len(path):]) for issue, aborted in errors] for parsed, errors in results]
        return value, [(dict(code='invalid_union', errors=nested, path=list(path), message='Invalid input'), True)]
    raise RuntimeError('Unsupported pinned MCP schema kind: ' + kind)


def parse(name, value):
    parsed, errors = _parse(DEFINITIONS['schemas'][name], value)
    if errors:
        raise SchemaError([issue for issue, aborted in errors])
    return parsed
