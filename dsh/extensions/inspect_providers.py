"""Original Service/Event catalogs, scoped Tool discovery and native Host builtins."""
import json
from pathlib import Path
import re

from dsh.core.session.json import UNDEFINED

CATALOG = json.loads(Path(__file__).with_name('inspect_catalog.json').read_text(encoding='utf-8'))['catalogs']
SERVICE_API, EVENT_API, TYPE_API = [CATALOG[key] for key in ('SERVICE_API', 'EVENT_API', 'TYPE_API')]
HOST_EVENTS = [event for event in EVENT_API if not event['name'].startswith('cordis/')]

# These entries describe the actual Python closure in DynamicCordisRunner.
# They do not advertise the original Node VM's JS globals as available in Python.
HOST_BUILTIN_INSPECTION = [
    dict(name='ctx', description='Cordis Context passed to the Python plugin callable.', signatures=[
        'ctx.get(name: str)', 'ctx.on(name: str, listener)', 'ctx.provide(name: str, value)', 'ctx.effect(callback, label: str = "anonymous")']),
    dict(name='harness', description='Host helpers for package-private Client RPC and model-visible tools.', signatures=[
        'harness.handle(method: str, handler)', 'harness.defineTool(definition: dict)', 'harness.registerTool(ctx, tool)']),
    dict(name='plugin', description='Callable declared by the Host source and mounted by Cordis.', signatures=['def plugin(ctx): ...']),
    dict(name='__builtins__', description='Python 3.8 builtins; imports execute in the trusted Host process.', signatures=['print(*values)', '__import__(name)']),
]


def _closure(seeds):
    included, frontier = set(), list(seeds)
    while frontier:
        following = []
        for entry in TYPE_API:
            if entry['name'] in included:
                continue
            pattern = re.compile(r'\b' + re.escape(entry['name']) + r'\b', re.ASCII)
            if not any(pattern.search(text) for text in frontier):
                continue
            included.add(entry['name'])
            following.append(entry['declaration'])
        frontier = following
    return [entry for entry in TYPE_API if entry['name'] in included]


def query_service_api(key=UNDEFINED, services=None):
    services = SERVICE_API if services is None else services
    if key is UNDEFINED:
        return dict(mode='catalog', services=[dict(key=service['key'], description=service['summary'],
            methods=[dict(signature=method['signature']) for method in service['methods']]) for service in services])
    service = next((row for row in services if row['key'] == key), None)
    if service is None:
        raise ValueError('no catalogued Service named "{}"'.format(key))
    expression = 'ctx.' + key if re.fullmatch(r'[A-Za-z_$][\w$]*', key, re.ASCII) else 'ctx[' + json.dumps(key, ensure_ascii=False) + ']'
    return dict(mode='service', service=dict(key=key, description=service['description'], access=dict(
        optional=dict(expression='ctx.get(' + json.dumps(key, ensure_ascii=False) + ')', requiresUndefinedCheck=True),
        hardDependency=dict(inject=[key], expression=expression)), methods=service['methods']),
        referencedTypes=_closure([method['signature'] for method in service['methods']]))


def query_event_api(name=UNDEFINED, events=None):
    events = EVENT_API if events is None else events
    if name is UNDEFINED:
        return dict(mode='catalog', events=[dict(name=event['name'], description=event['summary'],
            mode=event['mode'], signature=event['signature']) for event in events])
    event = next((row for row in events if row['name'] == name), None)
    if event is None:
        raise ValueError('no catalogued Event named "{}"'.format(name))
    return dict(mode='event', event=dict(name=name, description=event['description'], mode=event['mode'],
        signature=event['signature'], parameters=event['parameters']), referencedTypes=_closure([event['signature']]))


def _exact(input, key):
    value = input.get(key) if isinstance(input, dict) else None
    return value if isinstance(value, str) else UNDEFINED


def host_inspect_providers(ctx):
    empty = dict(type='object', properties={}, additionalProperties=False)
    output = dict(description='JSON data owned by this inspect provider.')
    def registration(provider, description, method, query, input_schema=None, output_schema=None):
        def execute(name, input, context):
            if name != method:
                raise ValueError('unknown {} inspect method "{}"'.format(provider, name))
            return query(input, context)
        return dict(manifest=dict(id=provider, description=description, methods=[dict(name=method, description=description,
            inputSchema=empty if input_schema is None else input_schema,
            outputSchema=output if output_schema is None else output_schema)]), query=execute)
    def exact_input(key, description):
        return dict(type='object', properties={key: dict(type='string', description=description)}, additionalProperties=False)
    providers = [
        registration('Service', 'Progressive Host Service discovery: compact capability/signature directory, then one exact coding contract.',
            'listService', lambda input, _: query_service_api(_exact(input, 'service')),
            exact_input('service', 'Exact Service key. Omit it for the compact Service and method-signature directory.'),
            dict(description='Compact Service directory, or one exact Service contract with only its referenced type declarations.')),
        registration('Event', 'Progressive Host Event discovery: compact listener directory, then one exact event contract.',
            'listEvents', lambda input, _: query_event_api(_exact(input, 'event'), HOST_EVENTS),
            exact_input('event', 'Exact Event name. Omit it for the compact Event and listener-signature directory.'),
            dict(description='Compact Event directory, or one exact Event contract with only its referenced type declarations.')),
        registration('Builtin', 'Python symbols available to a dynamic Host half.', 'listBuiltins',
            lambda _input, _: dict(builtins=HOST_BUILTIN_INSPECTION, referencedTypes=[])),
    ]
    def query_tools(method, _input, context):
        if method != 'listTools':
            raise ValueError('unknown Tool inspect method "{}"'.format(method))
        return dict(tools=ctx.get('tools').schemas(context.agent))
    providers.append(dict(manifest=dict(id='Tool', description='Tools visible to the requesting Agent, including scoped and dynamic registrations.',
        methods=[dict(name='listTools', description='Return every Tool schema currently callable by this Agent.', inputSchema=empty, outputSchema=output)]),
        query=query_tools))
    return providers


hostInspectProviders = host_inspect_providers
queryServiceApi = query_service_api
queryEventApi = query_event_api
