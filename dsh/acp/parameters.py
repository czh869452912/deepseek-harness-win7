import copy
import json
import math

from dsh.acp.rpc import ABSENT, RequestError


SKIP = object()
from dsh.acp.parameter_schemas import PARAMETER_SCHEMAS as SCHEMAS


def value_type(value):
    if value is ABSENT:
        return 'undefined'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return 'number'


def failure(path, expected, value):
    return [(path, 'Invalid input: expected %s, received %s' % (expected, value_type(value)), True)]


def fallback(schema):
    value = schema['fallback']
    return ABSENT if value.get('absent') else SKIP if value.get('skip') else copy.deepcopy(value['value'])


def parse(schema, value, path=()):
    kind = schema['type']
    if kind == 'optional' and value is ABSENT or kind == 'nullable' and value is None:
        return value, []
    if kind in ('optional', 'nullable'):
        return parse(schema['inner'], value, path)
    if kind == 'default':
        return (fallback(schema), []) if value is ABSENT else parse(schema['inner'], value, path)
    if kind == 'catch':
        parsed, errors = parse(schema['inner'], value, path)
        return (fallback(schema), []) if errors else (parsed, [])
    if kind == 'unknown':
        return copy.deepcopy(value) if value is not ABSENT else value, []
    if kind in ('string', 'boolean'):
        if value_type(value) != kind:
            return value, failure(path, kind, value)
        return value, []
    if kind == 'number':
        if value_type(value) != 'number' or not math.isfinite(value):
            return value, failure(path, 'number', value)
        if schema.get('format') == 'safeint' and int(value) != value:
            return value, failure(path, 'int', value)
        errors = []
        if schema.get('format') == 'safeint' and abs(value) > 9007199254740991:
            errors.append((path, 'Too %s: expected int to be %s%s' % (
                'big' if value > 0 else 'small', '<=' if value > 0 else '>=',
                '9007199254740991' if value > 0 else '-9007199254740991'), False))
        for check in schema.get('checks', []):
            if check['check'] == 'greater_than' and value < check['value']:
                errors.append((path, 'Too small: expected number to be >=%s' % check['value'], False))
            elif check['check'] == 'less_than' and value > check['value']:
                errors.append((path, 'Too big: expected number to be <=%s' % check['value'], False))
        return value, errors
    if kind in ('literal', 'enum'):
        if any(type(value) is type(option) and value == option for option in schema['values']):
            return value, []
        options = [json.dumps(option, ensure_ascii=False, separators=(',', ':')) for option in schema['values']]
        message = 'Invalid input: expected ' + options[0] if len(options) == 1 else 'Invalid option: expected one of ' + '|'.join(options)
        return value, [(path, message, True)]
    if kind == 'object':
        if not isinstance(value, dict):
            return value, failure(path, 'object', value)
        result, errors = {}, []
        for name, field in schema['shape'].items():
            parsed, issues = parse(field, value.get(name, ABSENT), path + (name,))
            errors.extend(issues)
            if parsed is not ABSENT:
                result[name] = parsed
        return result, errors
    if kind == 'record':
        if not isinstance(value, dict):
            return value, failure(path, 'record', value)
        result, errors = {}, []
        for name, field in value.items():
            parsed, issues = parse(schema['value'], field, path + (name,))
            errors.extend(issues)
            result[name] = parsed
        return result, errors
    if kind == 'array':
        if not isinstance(value, list):
            return value, failure(path, 'array', value)
        result, errors = [], []
        for index, field in enumerate(value):
            parsed, issues = parse(schema['element'], field, path + (index,))
            result.append(parsed)
            errors.extend(issues)
        return result, errors
    if kind == 'skip-array':
        result, errors = parse(schema['inner'], value, path)
        return ([field for field in result if field is not SKIP], []) if not errors else (result, errors)
    if kind == 'required-mcp-array':
        if value is ABSENT:
            return value, [(path, 'Required value is missing', True)]
        if not isinstance(value, list):
            return [], []
        result = []
        for field in value:
            parsed, errors = parse(schema['element'], field, path)
            if not errors:
                result.append(parsed)
        return result, []
    if kind == 'intersection':
        left, left_errors = parse(schema['left'], value, path)
        right, right_errors = parse(schema['right'], value, path)
        result = dict(left, **right) if isinstance(left, dict) and isinstance(right, dict) else value
        return result, left_errors + right_errors
    if kind == 'union':
        results = [parse(option, value, path) for option in schema['options']]
        for parsed, errors in results:
            if not errors:
                return parsed, []
        nonaborted = [(parsed, errors) for parsed, errors in results if not any(issue[2] for issue in errors)]
        if len(nonaborted) == 1:
            return nonaborted[0]
        return value, [(location, message, True) for parsed, errors in results for location, message, aborted in errors]
    raise RuntimeError('Unsupported ACP schema: ' + kind)


def validate_params(method, value=ABSENT):
    parsed, errors = parse(SCHEMAS[method], value)
    if not errors:
        return parsed
    formatted = {'_errors': []}
    for path, message, aborted in errors:
        target = formatted
        for name in path:
            target = target.setdefault(str(name), {'_errors': []})
        target['_errors'].append(message)
    raise RequestError(-32602, 'Invalid params', formatted)
