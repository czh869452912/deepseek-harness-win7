"""Python PTC prompt projection from the admitted tools' canonical schemas.

Declarations are advisory text, not code imported into the worker. Identifier
decisions use the target interpreter's Unicode tables so every emitted name is
parseable on Python 3.8, including when the Source engine has newer tables.
"""
import re
import unicodedata

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_own_enumerable_keys, js_to_string
from dsh.core.json_schema import assert_supported_json_schema

_RESERVED = frozenset(('False None True and as assert async await break class '
    'continue def del elif else except finally for from global if import in is '
    'lambda nonlocal not or pass raise return try while with yield __debug__').split())
_TYPING_ORDER = ('Any', 'Literal', 'NotRequired', 'Protocol', 'TypedDict')
# ECMAScript whitespace, deliberately not Python's broader str.isspace().
_SPACE = re.compile('[\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+')
_CONTROLS = re.compile('[\u0000-\u0008\u000e-\u001f\u007f-\u009f]')
_SURROGATES = re.compile('[\ud800-\udfff]')
# Python 3.8's old parser has a lower stack budget than the modern parser
# targeted by Source's 180-bracket limit. Reserve room for the parameter list,
# NotRequired and Literal wrappers. These are static stubs, never imported.
MAX_LIST_NESTING = 80


def _bare(name):
    return name.isidentifier() and unicodedata.normalize('NFKC', name) == name


def _describe(schema):
    value = schema.get('description')
    if not isinstance(value, str):
        return None
    value = _SPACE.sub(' ', value)
    value = _CONTROLS.sub(lambda m: '\\x%02x' % ord(m[0]), value)
    value = _SURROGATES.sub(lambda m: '\\u%04x' % ord(m[0]), value).strip(' ')
    return value or None


def _camel(raw):
    parts, part = [], ''
    for char in raw:
        if char != '_' and ('a' + char).isidentifier():
            part += char
        elif part:
            parts.append(part)
            part = ''
    if part:
        parts.append(part)
    joined = unicodedata.normalize('NFKC', ''.join(p[0].upper() + p[1:] for p in parts))
    # An underscore is a separator above, not XID_Start here.
    if not joined or not joined[0].isidentifier() or joined[0] == '_':
        joined = 'Tool' + joined
    return unicodedata.normalize('NFKC', joined)


def _cap(base):
    return base.encode('utf-16-le', 'surrogatepass')[:240].decode('utf-16-le', 'ignore')


def _child(base, segment):
    return _cap(unicodedata.normalize('NFKC', base + segment))


class _State:
    def __init__(self):
        self.classes = []
        self.used = set()
        self.next = {}
        self.typing = set()

    def allocate(self, base):
        base = _cap(base)
        name = base
        if name in self.used:
            number = self.next.get(base, 2)
            while base + str(number) in self.used:
                number += 1
            name = base + str(number)
            self.next[base] = number + 1
        self.used.add(name)
        return name


def _scalar(value):
    if value is True:
        return 'True'
    if value is False:
        return 'False'
    if isinstance(value, str):
        return stringify_json(value)
    if abs(value) > 9007199254740991 and value == int(value):
        return str(int(value))
    return js_to_string(value)


def _render(schema, class_name, state):
    # Validate once before emission; walk iteratively so deep schemas do not
    # depend on the host interpreter's recursion limit.
    try:
        assert_supported_json_schema(schema)
    except (TypeError, ValueError):
        state.typing.add('Any')
        return 'Any'

    def frame(node, name, depth):
        return dict(node=node, name=name, depth=depth, phase='start', children=[], types=[], index=0)

    frames = [frame(schema, class_name, 0)]
    result = None

    def finish(value):
        nonlocal result
        frames.pop()
        if frames:
            frames[-1]['types'].append(value)
        else:
            result = value

    while frames:
        current = frames[-1]
        node, name, depth = current['node'], current['name'], current['depth']
        if current['phase'] == 'children':
            if current['index'] < len(current['children']):
                child = current['children'][current['index']]
                current['index'] += 1
                frames.append(frame(*child))
                continue
            kind = current['kind']
            if kind == 'oneOf':
                finish(' | '.join(current['types']))
            elif kind == 'array':
                finish('list[' + current['types'][0] + ']')
            else:
                allocated = current['allocated']
                required = set(node.get('required', []))
                lines = ['class %s(TypedDict):' % allocated]
                for (field, child), annotation in zip(current['entries'], current['types']):
                    description = _describe(child)
                    if description:
                        lines.append('    # ' + description)
                    if field not in required:
                        state.typing.add('NotRequired')
                        annotation = 'NotRequired[' + annotation + ']'
                    lines.append('    %s: %s' % (field, annotation))
                if node.get('additionalProperties') is not False:
                    lines.append('    # Additional keys beyond those declared are allowed.')
                if len(lines) == 1:
                    lines.append('    pass')
                state.classes.append('\n'.join(lines))
                finish(allocated)
            continue
        current['phase'] = 'children'
        if 'oneOf' in node:
            current['kind'] = 'oneOf'
            current['children'] = [(branch, _child(name, str(i + 1)), depth)
                                   for i, branch in enumerate(node['oneOf'])]
            continue
        kind = node.get('type')
        if kind in ('string', 'number', 'integer', 'boolean'):
            if 'const' in node or 'enum' in node:
                state.typing.add('Literal')
                values = [node['const']] if 'const' in node else node['enum']
                finish('Literal[' + ', '.join(_scalar(v) for v in values) + ']')
            else:
                finish(dict(string='str', number='float', integer='int', boolean='bool')[kind])
        elif kind == 'null':
            finish('None')
        elif kind == 'array':
            if 'items' not in node or depth >= MAX_LIST_NESTING:
                state.typing.add('Any')
                finish('list[Any]' if 'items' not in node else 'Any')
            else:
                current['kind'] = 'array'
                current['children'] = [(node['items'], name, depth + 1)]
        elif kind == 'object':
            properties = node.get('properties', {})
            entries = [(key, properties[key]) for key in _js_own_enumerable_keys(properties)]
            expressible = class_name and all(_bare(key) and key not in _RESERVED
                and not (key.startswith('__') and not key.endswith('__')) for key, _ in entries)
            if not expressible or (not entries and node.get('additionalProperties') is not False):
                state.typing.add('Any')
                finish('dict[str, Any]')
                continue
            allocated = state.allocate(name)
            state.typing.add('TypedDict')
            current.update(kind='typeddict', entries=entries, allocated=allocated,
                children=[(child, _child(allocated, _camel(field)), 1) for field, child in entries])
        else:
            state.typing.add('Any')
            finish('Any')
    return result


def json_schema_to_py(schema):
    return _render(schema, '', _State())


SDK_INSTRUCTIONS = '''## Writing code for run_code

`run_code` takes two required arguments: `code`, the program to execute, and `description`, a short summary of what the program does. At run time exactly two of the names declared below are bound: `tools` and `ToolCallError`. Everything else is a STATIC STUB describing argument and return types — in particular the `TypedDict` classes do NOT exist at run time, so build arguments as plain `dict`/`list` JSON values: `await tools.name({"field": 1})`, never `FooArgs(field=1)`, which raises `NameError`. Inside the program:

- Call tools as `await tools.name(args)` — subscript access for exotic, reserved, or underscore-leading names: `await tools["my-tool"](args)`. Every call resolves to the tool's typed canonical JSON value (each method's return type below). Tool arguments must be lossless JSON.
- A FAILED tool call raises `ToolCallError`, whose `toolName` identifies the failed tool and whose message is human-readable — wrap in `try/except` to handle and continue.
- Independent read-only calls MAY overlap under `asyncio.gather` (safe calls run concurrently; mutating calls run alone, in submission order). Sequence dependent work with `await`.
- Only values emitted as program output enter the conversation. A successful tool result containing an image is attached after the run so you can inspect it on the next step; every other intermediate result stays out of the conversation, so extract just what you need.

The available tools:'''


def render_tools_sdk_py(schemas):
    state = _State()
    state.typing.add('Protocol')
    members, statements = [], 0
    # JS compares UTF-16 code units rather than Unicode code points.
    for schema in sorted(schemas, key=lambda s: s['name'].encode('utf-16-be', 'surrogatepass')):
        name = schema['name']
        args = _render(schema.get('parameters'), _camel(name) + 'Args', state)
        output = _render(schema.get('output'), _camel(name) + 'Output', state)
        description = _describe(schema)
        if _bare(name) and name not in _RESERVED and not name.startswith('_'):
            method = '    async def %s(self, args: %s) -> %s:' % (name, args, output)
            if description:
                members.extend([method, '        """' + description.replace('\\', '\\\\').replace('"', '\\"') + '"""'])
            else:
                members.append(method + ' ...')
            statements += 1
        else:
            members.append('    # tools[%s](args: %s) -> %s' % (stringify_json(name), args, output))
            if description:
                members.append('    #   ' + description)
    if not statements:
        members.insert(0, '    pass')
    imports = ', '.join(symbol for symbol in _TYPING_ORDER if symbol in state.typing)
    classes = '\n\n'.join(state.classes) + '\n\n' if state.classes else ''
    return (SDK_INSTRUCTIONS + '\n\n```python\nfrom typing import ' + imports
        + '\n\nclass ToolCallError(Exception):\n    toolName: str\n\n' + classes
        + 'class Tools(Protocol):\n' + '\n'.join(members) + '\n\ntools: Tools\n```')


jsonSchemaToPy = json_schema_to_py
renderToolsSdkPy = render_tools_sdk_py
