"""Native equivalent of the pinned dynamic Host registration/Context facade.

This guards ordinary plugin API use; trusted Python execution is not a sandbox
for malicious code. JavaScript VM/global behavior is a separate compatibility
contract. Traversals are iterative to retain the source's deep-data behavior.
"""
import inspect
import math
import weakref

from dsh.cordis.context import Context
from dsh.cordis.utils import _js_own_enumerable_keys, js_to_string
from dsh.core.json_schema import JsonSchemaError, assert_supported_json_schema, validate_json_schema_value, _dump
from dsh.core.scope import scope_of
from dsh.core.session.json import FrozenDict, FrozenList, UNDEFINED
from dsh.llm.error import HarnessError

ANNOTATIONS = ('description', 'title', 'default', 'examples')
TYPES = ('string', 'number', 'integer', 'boolean', 'null', 'object', 'array', 'json')
VALID_TYPES = "'string' | 'number' | 'integer' | 'boolean' | 'null' | 'object' | 'array' | 'json'"
CTX_VERBS = {'effect', 'on', 'once', 'provide', 'timeout', 'interval', 'setTimeout', 'setInterval', 'throttle', 'debounce'}
TIMER_VERBS = {'timeout', 'interval', 'setTimeout', 'setInterval', 'throttle', 'debounce'}
_marked = weakref.WeakValueDictionary()
_tool_contexts = weakref.WeakKeyDictionary()
_guarded_services = weakref.WeakKeyDictionary()
_contexts = weakref.WeakKeyDictionary()


def record(value):
    return type(value) in (dict, FrozenDict)


def array(value):
    return type(value) in (list, FrozenList)


def keys(value):
    return _js_own_enumerable_keys(value)


def clone_json(value, path):
    holder, ancestors = [None], set()
    tasks = [('visit', value, path, holder, 0)]
    while tasks:
        task = tasks.pop()
        if task[0] == 'leave':
            ancestors.remove(task[1])
            continue
        _, current, at, parent, key = task
        kind = type(current)
        scalar = current is None or kind in (str, bool)
        if kind in (int, float):
            try:
                scalar = math.isfinite(current) and not (current == 0 and math.copysign(1, current) < 0)
            except OverflowError:
                scalar = False
        if scalar:
            parent[key] = current
            continue
        if (not record(current) and not array(current)) or id(current) in ancestors or (
                record(current) and any(type(k) is not str for k in current)):
            if inspect.iscoroutine(current):
                current.close()
            raise ValueError(at + ' must be lossless JSON data (objects, arrays, strings, numbers, booleans, null) — '
                'not a class instance, function, Map/Set, Date, or undefined. Return a plain object built from the '
                'values you need, or `return null` when the caller needs no value back.')
        ancestors.add(id(current))
        tasks.append(('leave', id(current)))
        output = {} if record(current) else [None] * len(current)
        parent[key] = output
        entries = [(k, current[k], at + '.' + k) for k in keys(current)] if record(current) else [
            (index, child, '{}[{}]'.format(at, index)) for index, child in enumerate(current)]
        for child_key, child, child_path in reversed(entries):
            tasks.append(('visit', child, child_path, output, child_key))
    return holder[0]


def schema_keys(value, path, allowed):
    if any(type(k) is not str for k in value):
        raise ValueError('harness.defineTool ' + path + ' must contain only own enumerable string keys')
    for key in keys(value):
        if key not in allowed:
            raise ValueError('harness.defineTool {}.{} is not supported by the unified schema DSL'.format(path, key))


def annotations(value, output, path):
    for key in ANNOTATIONS:
        if key in value:
            output[key] = clone_json(value[key], 'harness.defineTool ' + path + '.' + key) if key in ('default', 'examples') else value[key]


def required_names(value, properties, path):
    if value is UNDEFINED:
        return set()
    if not array(value) or any(type(name) is not str for name in value):
        raise ValueError('harness.defineTool ' + path + ' must be an array of declared property names')
    for name in value:
        if name not in properties:
            raise ValueError('harness.defineTool {} names undeclared property {}'.format(path, _dump(name)))
    return set(value)


def normalize_parameters(value):
    path, root_annotations, raw = 'parameters', {}, record(value) and value.get('type') == 'object'
    if not record(value):
        raise ValueError('harness.defineTool parameters must be a ParameterSchemaSpec object')
    required = set()
    if raw:
        schema_keys(value, path, ('type', 'properties', 'required', 'additionalProperties') + ANNOTATIONS)
        if not record(value.get('properties')):
            raise ValueError('harness.defineTool parameters.properties must be an object of schemas')
        if 'additionalProperties' in value and value['additionalProperties'] is not True:
            raise ValueError('harness.defineTool parameters.additionalProperties must be true or omitted because the implicit parameter root is open')
        if value.get('required') is UNDEFINED:
            raise ValueError('harness.defineTool parameters.required must be an array of declared property names')
        required = required_names(value.get('required', UNDEFINED), value['properties'], path + '.required')
        annotations(value, root_annotations, path)
        value = value['properties']
    result, ancestors = {}, set()
    tasks = [('map', value, path, required, result)]
    while tasks:
        task = tasks.pop()
        if task[0] == 'leave':
            ancestors.remove(task[1])
            continue
        if task[0] == 'map':
            _, entries, at, required, output = task
            if id(entries) in ancestors:
                raise ValueError('harness.defineTool ' + at + ' is circular')
            schema_keys(entries, at, tuple(entries))
            ancestors.add(id(entries))
            tasks.append(('leave', id(entries)))
            for key in reversed(keys(entries)):
                tasks.append(('value', entries[key], at + '.' + key, key in required, True, output, key))
            continue
        _, node, at, force, parameter, parent, key = task
        if not record(node):
            raise ValueError('harness.defineTool ' + at + ' must be a ParameterSchemaSpec property object')
        schema_keys(node, at, tuple(node))
        if id(node) in ancestors:
            raise ValueError('harness.defineTool ' + at + ' is circular')
        ancestors.add(id(node))
        tasks.append(('leave', id(node)))
        if parameter and raw and 'required' in node and node.get('type') != 'object':
            raise ValueError('harness.defineTool ' + at + '.required belongs to the containing raw object schema')
        if parameter and not raw and 'required' in node and node['required'] is not True:
            raise ValueError('harness.defineTool ' + at + '.required must be true when present')
        prop = {}
        parent[key] = prop
        if force or node.get('required') is True:
            prop['required'] = True
        annotations(node, prop, at)
        allowed_required = ('required',) if parameter and not raw else ()
        if 'oneOf' in node:
            schema_keys(node, at, ('oneOf',) + allowed_required + ANNOTATIONS)
            branches = node['oneOf']
            if not array(branches) or len(branches) < 2:
                raise ValueError('harness.defineTool ' + at + '.oneOf must contain at least two schemas')
            prop['oneOf'] = [None] * len(branches)
            for index in range(len(branches) - 1, -1, -1):
                tasks.append(('value', branches[index], '{}.oneOf[{}]'.format(at, index), False, False, prop['oneOf'], index))
            continue
        if raw and 'type' not in node:
            schema_keys(node, at, ANNOTATIONS)
            prop['type'] = 'json'
            continue
        kind = node.get('type', UNDEFINED)
        if kind not in TYPES or raw and kind == 'json':
            shown = 'undefined' if kind is UNDEFINED else _dump(kind)
            raise ValueError('harness.defineTool {} must declare a valid type: {} (got {})'.format(at, VALID_TYPES, shown))
        prop['type'] = kind
        base = ('type',) + allowed_required + ANNOTATIONS
        if kind == 'object':
            schema_keys(node, at, base + ('properties', 'additionalProperties') + (('required',) if raw else ()))
            if not raw and type(node.get('additionalProperties')) is not bool:
                raise ValueError('harness.defineTool ' + at + '.additionalProperties must be explicitly true or false')
            if raw and 'additionalProperties' in node and type(node['additionalProperties']) is not bool:
                raise ValueError('harness.defineTool ' + at + '.additionalProperties must be a boolean')
            if raw and node.get('required') is UNDEFINED:
                raise ValueError('harness.defineTool ' + at + '.required must be an array of declared property names')
            prop['additionalProperties'] = node.get('additionalProperties', True)
            if 'properties' in node:
                properties = node['properties']
                if not record(properties):
                    raise ValueError('harness.defineTool ' + at + '.properties must be an object of schemas')
                nested = required_names(node.get('required', UNDEFINED), properties, at + '.required') if raw else set()
                prop['properties'] = {}
                tasks.append(('map', properties, at + '.properties', nested, prop['properties']))
            elif raw and node.get('required', UNDEFINED) is not UNDEFINED:
                required_names(node['required'], {}, at + '.required')
        elif kind == 'array':
            schema_keys(node, at, base + ('items',))
            if 'items' in node:
                tasks.append(('value', node['items'], at + '.items', False, False, prop, 'items'))
        elif kind == 'json':
            schema_keys(node, at, base)
        else:
            schema_keys(node, at, base + ('enum', 'const'))
            if 'enum' in node:
                if not array(node['enum']) or not node['enum']:
                    raise ValueError('harness.defineTool ' + at + '.enum must be a non-empty array')
                prop['enum'] = clone_json(node['enum'], 'harness.defineTool ' + at + '.enum')
            if 'const' in node:
                prop['const'] = clone_json(node['const'], 'harness.defineTool ' + at + '.const')
    return result, root_annotations


def compile_schema(spec, parameters=False):
    """Pinned author DSL compiler, used after the dynamic normalization stage."""
    root, ancestors = {}, set()
    tasks = [('map', spec, 'parameters', root)] if parameters else [('node', spec, 'schema', root, False)]
    def fail(message):
        raise JsonSchemaError([message])
    while tasks:
        task = tasks.pop()
        if task[0] == 'leave':
            ancestors.remove(task[1])
            continue
        if task[0] == 'map-tail':
            _, output, required = task
            if required:
                output['required'] = required
            continue
        if task[0] == 'property':
            _, item, at, properties, key, required = task
            if not record(item):
                fail(at + ' must be a value schema object')
            if 'required' in item and item['required'] is not True:
                fail(at + '.required must be true when present')
            if item.get('required') is True:
                required.append(key)
            properties[key] = {}
            tasks.append(('node', item, at, properties[key], True))
            continue
        if task[0] == 'map':
            _, entries, at, output = task
            if not record(entries):
                fail(at + ' must be an object of value schemas')
            if id(entries) in ancestors:
                fail(at + ' is circular')
            ancestors.add(id(entries))
            tasks.append(('leave', id(entries)))
            properties, required = {}, []
            output['properties'] = properties
            tasks.append(('map-tail', output, required))
            for key in reversed(keys(entries)):
                tasks.append(('property', entries[key], at + '.' + key, properties, key, required))
            continue
        _, node, at, output, allow_required = task
        if not record(node):
            fail(at + ' must be a value schema object')
        if id(node) in ancestors:
            fail(at + ' is circular')
        ancestors.add(id(node))
        tasks.append(('leave', id(node)))
        kind = node.get('type')
        if 'oneOf' not in node and kind not in TYPES:
            fail(at + '.type must be string/number/integer/boolean/null/array/object/json, or use oneOf')
        base = ANNOTATIONS + (('required',) if allow_required else ()) + ('type',)
        allowed = base + (('oneOf',) if 'oneOf' in node else
            ('properties', 'additionalProperties') if kind == 'object' else ('items',) if kind == 'array' else
            ('enum', 'const') if kind in ('string', 'number', 'integer', 'boolean', 'null') else ())
        for key in keys(node):
            if key not in allowed:
                fail(at + '.' + key + ' is not supported by the value schema DSL')
        for key in ANNOTATIONS:
            if key in node:
                output[key] = node[key]
        if 'oneOf' in node:
            if 'type' in node:
                fail(at + ' cannot declare both type and oneOf')
            if not array(node['oneOf']):
                fail(at + '.oneOf must be an array of at least two value schemas')
            branches = [{} for _ in node['oneOf']]
            output['oneOf'] = branches
            for index in range(len(branches) - 1, -1, -1):
                tasks.append(('node', node['oneOf'][index], '{}.oneOf[{}]'.format(at, index), branches[index], False))
        elif kind == 'json':
            pass
        elif kind == 'object':
            if type(node.get('additionalProperties')) is not bool:
                fail(at + '.additionalProperties must be explicitly true or false')
            output.update(type='object', additionalProperties=node['additionalProperties'])
            if 'properties' in node:
                tasks.append(('map', node['properties'], at + '.properties', output))
        elif kind == 'array':
            output['type'] = kind
            if 'items' in node:
                output['items'] = {}
                tasks.append(('node', node['items'], at + '.items', output['items'], False))
        elif kind in ('string', 'number', 'integer', 'boolean', 'null'):
            output['type'] = kind
            if 'enum' in node:
                if not array(node['enum']):
                    fail(at + '.enum must be a non-empty array of scalar values')
                output['enum'] = list(node['enum'])
            if 'const' in node:
                output['const'] = node['const']
        else:
            fail(at + '.type must be string/number/integer/boolean/null/array/object/json, or use oneOf')
    if parameters:
        root = dict(type='object', **root)
    assert_supported_json_schema(root)
    return root


class _DynamicTool(dict):
    __slots__ = ('__weakref__',)


def assert_dynamic_tool(tool):
    if type(tool) is not _DynamicTool or _marked.get(id(tool)) is not tool:
        raise ValueError('dynamic tool registration must use a tool returned by harness.defineTool(...)')


def rendered_content(value):
    if array(value) and all(record(item) and type(item.get('type')) is str for item in value):
        return value
    preview = _dump(value)
    encoded = preview.encode('utf-16-le', 'surrogatepass')
    if len(encoded) > 240:
        preview = encoded[:240].decode('utf-16-le', 'surrogatepass') + '…'
    raise ValueError('output.render returned ' + preview + ' — it must return an ARRAY of content blocks:\n'
        "  ✓ return [{ type: 'text', text: String(value) }]")


def sandbox_define_tool(options):
    if not record(options):
        raise ValueError('harness.defineTool options must be an object')
    normalized, root_annotations = normalize_parameters(options.get('parameters'))
    output = options.get('output')
    if not record(output):
        raise ValueError('harness.defineTool output must declare { schema, render, presentationMeta? }')
    if not callable(output.get('render')):
        raise ValueError('harness.defineTool output.render must be a function')
    meta = output.get('presentationMeta', UNDEFINED)
    if meta is not UNDEFINED and not callable(meta):
        raise ValueError('harness.defineTool output.presentationMeta must be a function when present')
    if not callable(options.get('execute')):
        raise ValueError('harness.defineTool execute must be a function')
    schema = clone_json(output.get('schema', UNDEFINED), 'harness.defineTool output.schema')
    timeout = options.get('timeoutMs', UNDEFINED)
    if timeout is not UNDEFINED and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('defineTool({}): timeoutMs must be a positive finite number'.format(js_to_string(options.get('name', UNDEFINED))))
    parameters = compile_schema(normalized, True)
    output_schema = compile_schema(schema)
    # The execute/presentation closures validate the compiled unannotated root,
    # as source defineTool does before guard.ts installs root annotations.
    validation_parameters = parameters
    parameters = dict(parameters, **root_annotations)
    assert_supported_json_schema(parameters)
    raw_execute, raw_render = options['execute'], output['render']
    async def execute(args, execution):
        violations = validate_json_schema_value(validation_parameters, args, '')
        if violations:
            error = HarnessError('invalid arguments: ' + '; '.join(violations), 'INVALID_ARGS')
            error.name, error.violations = 'ToolArgsError', violations
            raise error
        value = raw_execute(args, execution)
        if inspect.isawaitable(value):
            value = await value
        return clone_json(value, 'harness.defineTool execute result')
    guarded_output = dict(schema=output_schema, render=lambda args, value: rendered_content(clone_json(raw_render(args, value), 'harness.defineTool output.render result')))
    if meta is not UNDEFINED:
        guarded_output['presentationMeta'] = lambda args, value: clone_json(meta(args, value), 'harness.defineTool output.presentationMeta result')
    tool = _DynamicTool(name=options.get('name', UNDEFINED), description=options.get('description', UNDEFINED),
        parameters=parameters, output=guarded_output, execute=execute)
    if timeout is not UNDEFINED:
        tool['timeoutMs'] = timeout
    if options.get('finalizeContent'):
        tool['finalizeContent'] = options['finalizeContent']
    for name in ('presentCall', 'presentResult', 'isConcurrencySafe'):
        callback = options.get(name)
        if callback:
            def wrapped(args, *rest, callback=callback, classifier=name == 'isConcurrencySafe'):
                if validate_json_schema_value(validation_parameters, args, ''):
                    return False if classifier else UNDEFINED
                return callback(args, *rest)
            tool[name] = wrapped
    _marked[id(tool)] = tool
    return tool


def sandbox_register_tool(ctx, tool):
    assert_dynamic_tool(tool)
    actual = _contexts[ctx][0] if isinstance(ctx, SandboxContext) else ctx
    return actual.tools.register(tool)


def normalize_handler(method, handler):
    if not isinstance(method, str) or not method:
        raise ValueError('harness.handle(method, fn) needs a non-empty string method name')
    if not callable(handler):
        raise ValueError('harness.handle("{}") needs a handler function as its second argument'.format(method))
    async def normalized(args):
        value = handler(args)
        if inspect.isawaitable(value):
            value = await value
        return clone_json(value, 'harness.handle("{}") result'.format(method))
    return method, normalized


class SandboxTools:
    __slots__ = ('__weakref__',)
    def __init__(self, ctx):
        _tool_contexts[self] = ctx
    def register(self, tool):
        return sandbox_register_tool(_tool_contexts[self], tool)
    def schemas(self):
        ctx = _tool_contexts[self]
        return ctx.tools.schemas(scope_of(ctx))
    def get(self, name):
        return next((row for row in self.schemas() if row['name'] == name), None)


def deny_context(value, service, report):
    if isinstance(value, Context):
        error = ValueError('service "{}" returned a cordis Context, which the sandbox does not expose. '
            'Operate through your own plugin ctx (ctx.on / ctx.provide / ctx.tools.register) '
            'and the services you inject — never another context.'.format(service))
        report(error)
        raise error
    return value


def guard_service_member(value, name, report):
    if not callable(value):
        return deny_context(value, name, report)
    def call(*args, **kwargs):
        returned = value(*args, **kwargs)
        if inspect.isawaitable(returned):
            async def wait():
                return deny_context(await returned, name, report)
            return wait()
        return deny_context(returned, name, report)
    return call


class GuardedService:
    __slots__ = ('__weakref__',)
    def __init__(self, service, name, report):
        _guarded_services[self] = service, name, report
    def __getattr__(self, key):
        service, name, report = _guarded_services[self]
        value = service.get(key, UNDEFINED) if record(service) else getattr(service, key)
        return guard_service_member(value, name, report)
    def __setattr__(self, key, value):
        service = _guarded_services[self][0]
        if record(service):
            service[key] = value
        else:
            setattr(service, key, value)
    def __getitem__(self, key):
        service, name, report = _guarded_services[self]
        value = service[key] if record(service) or array(service) or not isinstance(key, str) else getattr(service, key)
        return guard_service_member(value, name, report)
    def __setitem__(self, key, value):
        service = _guarded_services[self][0]
        if record(service) or array(service) or not isinstance(key, str):
            service[key] = value
        else:
            setattr(service, key, value)
    def __call__(self, *args, **kwargs):
        service, name, report = _guarded_services[self]
        returned = service(*args, **kwargs)
        if inspect.isawaitable(returned):
            async def wait():
                return deny_context(await returned, name, report)
            return wait()
        return deny_context(returned, name, report)


class SandboxContext:
    __slots__ = ('__weakref__',)
    def __init__(self, ctx, report):
        _contexts[self] = ctx, SandboxTools(ctx), set(ctx.fiber.inject), report
    def __setattr__(self, name, value):
        error = ValueError('sandbox ctx is read-only; cannot assign "{}"'.format(name))
        _contexts[self][3](error)
        raise error
    def get(self, name):
        ctx, tools, _, report = _contexts[self]
        if name == 'tools':
            return tools
        value = deny_context(ctx.get(name), name, report)
        return value if value is None or type(value) in (str, bool, int, float) else GuardedService(value, name, report)
    def __getattr__(self, name):
        ctx, tools, declared, _ = _contexts[self]
        if name == 'tools':
            return tools
        if name in CTX_VERBS:
            def invoke(*args, **kwargs):
                if name in TIMER_VERBS and 'timer' not in declared:
                    deny_read(self, 'timer')
                return getattr(ctx, name)(*args, **kwargs)
            return invoke
        if name not in declared:
            return deny_read(self, name)
        return self.get(name)
    def __contains__(self, name):
        declared = _contexts[self][2]
        return name in ('tools', 'get') or name in declared or name in CTX_VERBS and (name not in TIMER_VERBS or 'timer' in declared)


def deny_read(facade, name):
    ctx, _, _, report = _contexts[facade]
    if ctx.get(name) is not None:
        text = 'service "{}" is not injected. Declare it: inject: [\'{}\', …] on your plugin, so cordis parks this dynamic package if the provider later goes away.'.format(name, name)
    else:
        text = 'sandbox ctx does not expose "{}". Available: ctx.tools.register / ctx.on / ctx.provide / the timer helpers after injecting timer, and any service you declared in inject. Framework internals (root, fiber, registry, extend, plugin, …) are withheld by design.'.format(name)
    error = ValueError(text)
    report(error)
    raise error


def guarded_plugin(plugin, report):
    raw_apply = plugin if callable(plugin) else plugin['apply']
    def apply(ctx, *args):
        facade = SandboxContext(ctx, report)
        try:
            signature = inspect.signature(raw_apply)
        except (ValueError, TypeError):
            return raw_apply(facade, *args)
        try:
            signature.bind(facade, *args)
        except TypeError:
            signature.bind(facade)
            return raw_apply(facade)
        return raw_apply(facade, *args)
    # Python function metadata is the native plugin's inject declaration.
    wrapped = dict(vars(plugin)) if callable(plugin) else dict(plugin)
    wrapped.update(name=getattr(plugin, 'name', '<anonymous>') if callable(plugin) else plugin.get('name', '<anonymous>'), apply=apply)
    return wrapped
