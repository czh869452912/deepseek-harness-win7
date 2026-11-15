"""TypeScript SDK prompt projection; no TypeScript runtime dependency."""
import re

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.core.json_schema import assert_supported_json_schema
from dsh.core.ptc_sdk import _SPACE

_IDENTIFIER = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')


def _key(name):
    return name if _IDENTIFIER.fullmatch(name) else stringify_json(name)


def _docs(description, indent):
    if not isinstance(description, str) or not description:
        return []
    return ['  ' * indent + '/** ' + _SPACE.sub(' ', description).strip(' ').replace('*/', '*\\/') + ' */']


class _Document:
    def __init__(self, *parts):
        self.parts = parts
        self.union = any(part.union if isinstance(part, _Document) else '|' in part or '&' in part for part in parts)

    def flatten(self):
        chunks, tasks = [], [self]
        while tasks:
            part = tasks.pop()
            if isinstance(part, str):
                chunks.append(part)
            else:
                tasks.extend(reversed(part.parts))
        return ''.join(chunks)


def json_schema_to_ts(schema, indent=0):
    try:
        assert_supported_json_schema(schema)
    except (TypeError, ValueError):
        return 'unknown'
    def frame(node, level):
        return dict(node=node, indent=level, phase='start', children=[], results=[], index=0)
    frames, result = [frame(schema, indent)], None
    def finish(document):
        nonlocal result
        frames.pop()
        if frames:
            frames[-1]['results'].append(document)
        else:
            result = document
    while frames:
        current = frames[-1]
        node, level = current['node'], current['indent']
        if current['phase'] == 'children':
            if current['index'] < len(current['children']):
                child = current['children'][current['index']]
                current['index'] += 1
                frames.append(frame(*child))
                continue
            kind, results = current['kind'], current['results']
            if kind == 'oneOf':
                parts = []
                for index, child in enumerate(results):
                    if index:
                        parts.append(' | ')
                    parts.append(child)
                finish(_Document(*parts))
            elif kind == 'array':
                child = results[0]
                finish(_Document('(', child, ')[]') if child.union else _Document(child, '[]'))
            else:
                required = set(node.get('required', []))
                parts = ['{']
                for (name, prop), child in zip(current['entries'], results):
                    for line in _docs(prop.get('description'), level+1):
                        parts.extend(['\n', line])
                    parts.extend(['\n', '  '*(level+1) + _key(name) + ('' if name in required else '?') + ': ', child, ';'])
                parts.extend(['\n', '  '*level + '}'])
                declared = _Document(*parts)
                finish(declared if node.get('additionalProperties') is False else _Document(declared, ' & Record<string, JsonValue>'))
            continue
        if 'oneOf' in node:
            current.update(phase='children', kind='oneOf', children=[(child, level) for child in node['oneOf']])
            continue
        kind = node.get('type')
        if kind in ('string', 'number', 'integer', 'boolean', 'null'):
            if 'const' in node:
                value = stringify_json(node['const'])
            elif 'enum' in node:
                value = ' | '.join(stringify_json(value) for value in node['enum'])
            else:
                value = 'number' if kind=='integer' else kind
            finish(_Document(value))
        elif kind == 'array':
            if 'items' not in node:
                finish(_Document('JsonValue[]'))
            else:
                current.update(phase='children', kind='array', children=[(node['items'], level)])
        elif kind == 'object':
            properties = node.get('properties', {})
            entries = [(key, properties[key]) for key in _js_own_enumerable_keys(properties)]
            if not entries:
                finish(_Document('Record<string, never>' if node.get('additionalProperties') is False else 'Record<string, JsonValue>'))
            else:
                current.update(phase='children', kind='object', entries=entries,
                    children=[(child, level+1) for _, child in entries])
        else:
            finish(_Document('JsonValue'))
    return result.flatten()


def _bash_example(schemas, program_format):
    bash = next((schema for schema in schemas if schema['name']=='bash'), None)
    if bash is None:
        return ''
    parameters = bash['parameters']
    if not isinstance(parameters, dict) or parameters.get('type') != 'object':
        return ''
    required = parameters.get('required', [])
    if any(name not in ('command', 'description') for name in required):
        return ''
    def accepts(name, literal):
        schema = parameters.get('properties', {}).get(name, {})
        return (schema.get('type') == 'string' and ('const' not in schema or schema['const'] == literal)
            and ('enum' not in schema or literal in schema['enum']))
    if not accepts('command', 'pwd'):
        return ''
    needs_description = 'description' in required
    if needs_description and not accepts('description', 'Show current directory'):
        return ''
    description = "description: 'Show current directory', " if needs_description else ''
    call = 'tools.bash({ ' + description + "command: 'pwd' })"
    program = 'return await ' + call if program_format == 'function-body' else 'console.log(await ' + call + ')'
    return (' When no separate `bash` schema is supplied, invoke a declared `bash` binding inside `run_code`:\n\n'
        '`run_code({ code: "' + program + '", description: "Show current directory" })`')


def render_tools_sdk(schemas, program_format='function-body'):
    schemas = sorted(schemas, key=lambda schema: schema['name'].encode('utf-16-be', 'surrogatepass'))
    args, outputs = [], []
    for schema in schemas:
        args.extend(_docs(schema.get('description'), 1))
        args.append('  ' + _key(schema['name']) + ': ' + json_schema_to_ts(schema.get('parameters'), 1) + ';')
        outputs.append('  ' + _key(schema['name']) + ': ' + json_schema_to_ts(schema.get('output'), 1) + ';')
    maps = ['interface ' + name + ' {' + ('\n'+'\n'.join(members)+'\n' if members else '') + '}'
            for name, members in (('ToolArgsMap', args), ('ToolOutputMap', outputs))]
    declaration = '\n\n'.join(maps + ['type ToolName = keyof ToolOutputMap',
        'declare class ToolCallError extends Error {\n  readonly name: "ToolCallError";\n  readonly toolName: ToolName;\n}',
        'declare const tools: {\n  [K in ToolName]: (args: ToolArgsMap[K]) => Promise<ToolOutputMap[K]>;\n}'])
    program = ('the body of an async TypeScript function (erasable syntax only — no `enum` or namespaces; '
        'type annotations are advisory, the code runs type-stripped)' if program_format=='function-body' else 'the program to execute')
    instructions = ('## Writing code for run_code\n\n`run_code` takes two required arguments: `code`, ' + program
        + ', and `description`, a short summary of what the program does. The declarations below are SDK bindings '
        'for this program. A declaration does not make its name a directly callable tool; only names supplied '
        'as separate tool schemas may be called directly.')
    output = ('Emit results with `return` and/or `console.log(...)`. Only what you print or return is program output.'
        if program_format=='function-body' else 'Only values emitted as program output enter the conversation.')
    program_instructions = '''Inside the program:

- Call tools as `await tools.name(args)` — quoted access for exotic names: `tools["my-tool"](args)`. Every call resolves to the tool's typed canonical JSON value. Tool arguments must be lossless JSON.
- A FAILED tool call rejects with `ToolCallError`, whose `toolName` identifies the failed tool and whose `message` is human-readable — `try/catch` it to handle and continue.
- Independent read-only calls MAY overlap under `Promise.all` (safe calls run concurrently; mutating calls run alone, in submission order). Sequence dependent work with `await`.
- ''' + output + ''' A successful tool result containing an image is attached after the run so you can inspect it on the next step; every other intermediate result stays out of the conversation, so extract just what you need.

Program-only SDK bindings:'''
    return (instructions + _bash_example(schemas, program_format) + '\n\n' + program_instructions
        + '\n\n```ts\ntype JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }\n\n'
        + declaration + '\n```')


jsonSchemaToTs = json_schema_to_ts
renderToolsSdk = render_tools_sdk
