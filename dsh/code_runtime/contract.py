"""Binding validation and exact UTF-8 JSON output budgets."""
import json
import math
import re


RESERVED = set('await break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static implements interface package private protected public arguments eval False None True and as assert async def del elif except from global is lambda nonlocal not or pass raise match type _'.split())
OWNED = {'console', '__dsh_main__', '__builtins__', '__name__', '__debug__'}
ERROR_MEMBERS = {'name', 'message', 'stack', 'args', 'with_traceback', 'add_note'}
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def validate_bindings(bindings):
    if not isinstance(bindings, list):
        raise ValueError('bindings must be an array')
    names, result = set(), {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError('binding namespace must be an object')
        name = binding.get('global')
        validate_name(name)
        if name in names:
            raise ValueError('duplicate binding global ' + name)
        functions = binding.get('functions')
        if not isinstance(functions, dict) or any(not isinstance(k, str) or not callable(v) for k, v in functions.items()):
            raise ValueError('binding functions must map strings to callables')
        names.add(name)
        result[name] = dict(binding, functions=dict(functions))
    for binding in result.values():
        descriptor = binding.get('errorClass')
        if descriptor is None:
            continue
        if not isinstance(descriptor, dict):
            raise ValueError('binding errorClass must be an object')
        name = descriptor.get('name')
        validate_name(name)
        if name in names:
            raise ValueError('duplicate injected global ' + name)
        names.add(name)
        member = descriptor.get('memberNameProperty')
        if not isinstance(member, str) or not member or member in ERROR_MEMBERS or re.match(r'^__.+__$', member):
            raise ValueError('unusable binding error member property')
        binding['errorClass'] = dict(descriptor)
    return result


def validate_name(name):
    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or name in RESERVED or name in OWNED:
        raise ValueError('unusable binding global {!r}'.format(name))


def snapshot_json(value):
    """Reject lossy Python values, cycles, non-string keys and non-finite numbers."""
    active = set()
    def visit(item):
        if item is None or type(item) in (str, bool):
            return item
        if type(item) in (int, float):
            if not math.isfinite(item) or (type(item) is int and int(float(item)) != item):
                raise ValueError('number is not lossless JSON')
            return item
        if type(item) not in (dict, list) or id(item) in active:
            raise ValueError('value is not lossless JSON')
        active.add(id(item))
        try:
            if type(item) is list:
                return [visit(child) for child in item]
            if any(type(key) is not str for key in item):
                raise ValueError('JSON object keys must be strings')
            return {key: visit(child) for key, child in item.items()}
        finally:
            active.remove(id(item))
    return visit(value)


def encoded(value):
    # Lone UTF-16 surrogates are legal JSON strings; JS JSON.stringify escapes
    # them, whereas UTF-8 cannot encode them directly. Preserve all other text.
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return raw.encode('utf-8', errors='backslashreplace')


def truncate_string(text, budget):
    lo, hi = 0, len(text)
    while lo < hi:
        middle = (lo + hi + 1) // 2
        if len(encoded(text[:middle])) <= budget:
            lo = middle
        else:
            hi = middle - 1
    return text[:lo]


class OutputLedger:
    def __init__(self, maximum):
        self.maximum, self.logs, self.bytes = maximum, [], 2

    def admit(self, text):
        size = len(encoded(text)) + bool(self.logs)
        if self.bytes + size > self.maximum:
            return False
        self.logs.append(text)
        self.bytes += size
        return True

    def result(self, value=None, has_value=False, error=None):
        size = len(encoded(error['message'])) if error is not None else len(encoded(value)) if has_value else 0
        if self.bytes + size > self.maximum:
            return self.limit()
        result = {'logs': list(self.logs)}
        if error is not None:
            result['error'] = error
        elif has_value:
            result['value'] = value
        return result

    def limit(self):
        message = 'outer output exceeded {} bytes'.format(self.maximum)
        message = truncate_string(message, self.maximum - 2)
        available, retained = self.maximum - len(encoded(message)), []
        for text in self.logs:
            remaining = available - len(encoded(retained)) - bool(retained)
            if remaining < 2:
                break
            piece = truncate_string(text, remaining)
            retained.append(piece)
            if piece != text:
                break
        return dict(logs=retained, error=dict(kind='output-limit', message=message))
