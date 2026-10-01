"""Observe native Inspect against the same recipes as the actual pinned source."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.json_schema import assert_supported_json_schema, assert_object_json_schema, validate_json_schema_value, JsonSchemaError
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_registry import CordisInspectRegistryService
from dsh.extensions.inspect_providers import host_inspect_providers, SERVICE_API, HOST_EVENTS, query_service_api, query_event_api

OWNER, FOREIGN = SimpleNamespace(id='owner'), SimpleNamespace(id='foreign')
EMPTY = dict(type='object', properties={}, additionalProperties=False)
OUTPUT = dict(type='object', properties=dict(value=dict(type='integer')), required=['value'], additionalProperties=False)


def manifest(provider='probe'):
    return dict(id=provider, description='Read-only probe', methods=[dict(name='read', description='Read', inputSchema=EMPTY, outputSchema=OUTPUT)])


def error(caught):
    if isinstance(caught, ThrownValueError):
        return dict(thrown=caught.value)
    return dict(message=getattr(caught, 'message', str(caught)), **(dict(name=caught.name, code=caught.code, violations=caught.violations) if isinstance(caught, JsonSchemaError) else {}))


async def attempt(fn):
    try:
        value = fn()
        if asyncio.iscoroutine(value):
            value = await value
        return dict(value=dict(undefined=True) if value is None or value is UNDEFINED else value)
    except Exception as caught:
        return dict(error=error(caught))


def recipe(spec, schema):
    name = spec.get('recipe')
    if not name:
        return spec['schema' if schema else 'value']
    if name == 'negative-zero':
        return dict(type='number', enum=[-0.0], const=-0.0) if schema else -0.0
    if name == 'infinite':
        return float('inf')
    if name == 'utf16-pair':
        return '\ud83d\ude00'
    if name.startswith('array-subclass'):
        class Exotic(list):
            pass
        return Exotic([1, 'bad' if name.endswith('child') else 2])
    if name == 'undefined':
        return dict(default=UNDEFINED) if schema else dict(a=UNDEFINED)
    if name == 'cycle':
        value = dict(type='array') if schema else {}
        value['items' if schema else 'self'] = value
        return value
    if name == 'shared':
        child = dict(type='string')
        return dict(type='object', properties=dict(a=child, b=child))
    raise ValueError(name)


async def tick():
    for _ in range(4):
        await asyncio.sleep(0)


async def registry_observation(spec):
    ctx = Context()
    registry = CordisInspectRegistryService(ctx)
    events, acks = [], []
    ctx.on('cordis/inspect-query', lambda request: events.append(dict(kind='request', **request)))
    def closed(request):
        events.append(dict(kind='closed', **request))
        acks.append(registry.resolveClientQuery(OWNER, request['requestId'], dict(ok=True, data=dict(value=999))))
    ctx.on('cordis/inspect-query-resolved', closed)
    try:
        name = spec['recipe']
        if name == 'manifest':
            cases = [dict(manifest(), id='\ufeff\u2003'), dict(manifest(), description=' '),
                dict(manifest(), methods=[dict(manifest()['methods'][0], name='')]),
                dict(manifest(), methods=[manifest()['methods'][0], manifest()['methods'][0]]),
                dict(manifest(), methods=[dict(manifest()['methods'][0], description='')]),
                dict(manifest(), methods=[dict(manifest()['methods'][0], inputSchema=dict(type='string', pattern='x'))])]
            failures = [await attempt(lambda candidate=candidate: registry.register(dict(manifest=candidate, query=lambda *_: {}))) for candidate in cases]
            first = registry.register(dict(manifest=manifest(), query=lambda *_: dict(value=1)))
            failures.append(await attempt(lambda: registry.register(dict(manifest=manifest(), query=lambda *_: dict(value=2)))))
            registry.syncClientManifest([manifest('client')])
            before = registry.list()
            failures.append(await attempt(lambda: registry.syncClientManifest([manifest('other'), manifest('other')])))
            retained = registry.list()
            first(); first()
            registry.register(dict(manifest=manifest(), query=lambda *_: dict(value=2))); first()
            return dict(failures=failures, before=before, retained=retained, after=registry.list())
        if name == 'host':
            result, after_call, inputs = dict(value=1), None, []
            async def handler(method, input, context):
                inputs.append(dict(input=dict(undefined=True) if input is UNDEFINED else input, owner=context.agent.id))
                if after_call:
                    after_call()
                return result
            registry.register(dict(manifest=manifest(), query=handler))
            def query(input=UNDEFINED, signal=NEVER_ABORTED):
                return registry.query('host', 'probe', 'read', input, OWNER, signal)
            null_input, omitted = await attempt(lambda: query(None)), await attempt(query)
            invalid_input = await attempt(lambda: query(dict(unexpected=1)))
            detached = await query(); result['value'] = 2
            result = dict(value='bad'); invalid_output = await attempt(query)
            result = dict(value=1, negative=-0.0); non_json = await attempt(query)
            result = {}; result['self'] = result; cyclic = await attempt(query)
            controller = AbortController(); after_call = lambda: controller.abort('post-abort')
            post_abort = await attempt(lambda: query(UNDEFINED, controller.signal))
            return dict(nullInput=null_input, omitted=omitted, invalidInput=invalid_input, detached=detached, invalidOutput=invalid_output,
                nonJson=non_json, cyclic=cyclic, postAbort=post_abort, inputs=inputs,
                missingProvider=await attempt(lambda: registry.query('host', 'missing', 'read', UNDEFINED, OWNER, NEVER_ABORTED)),
                missingMethod=await attempt(lambda: registry.query('host', 'probe', 'missing', UNDEFINED, OWNER, NEVER_ABORTED)))
        registry.syncClientManifest([manifest('client')])
        controller = AbortController()
        if name == 'abort':
            controller.abort('pre-abort')
            return dict(result=await attempt(lambda: registry.query('client', 'client', 'read', UNDEFINED, OWNER, controller.signal)), events=events)
        settled = False
        async def run():
            nonlocal settled
            outcome = await attempt(lambda: registry.query('client', 'client', 'read', None if name == 'inflight' else UNDEFINED, OWNER, controller.signal))
            settled = True
            return outcome
        pending = asyncio.create_task(run())
        await tick()
        request_id = events[0]['requestId']
        if name == 'client':
            responses = [registry.resolveClientQuery(FOREIGN, request_id, dict(ok=True, data=dict(value=1))),
                registry.resolveClientQuery(OWNER, request_id, dict(ok=False, reason='failed', message='other page failed')),
                registry.resolveClientQuery(OWNER, request_id, dict(ok=True, data=dict(value='bad'))),
                registry.resolveClientQuery(OWNER, request_id, dict(ok=True, data=dict(value=2))),
                registry.resolveClientQuery(OWNER, request_id, dict(ok=True, data=dict(value=3)))]
            result = await pending; controller.abort('late')
            return dict(responses=responses, result=result, events=events, acks=acks)
        if name == 'inflight':
            changed = manifest('client'); changed['methods'][0]['outputSchema'] = dict(type='string')
            registry.syncClientManifest([changed])
            accepted = registry.resolveClientQuery(OWNER, request_id, dict(ok=True, data=dict(value=4)))
            return dict(accepted=accepted, result=await pending, directory=registry.list(), events=events, acks=acks)
        if name == 'disposal':
            await ctx.fiber.dispose(); await tick()
            after_dispose = dict(pending=len(registry._pending), settled=settled, closed=sum(event['kind'] == 'closed' for event in events))
            controller.abort('cleanup')
            return dict(afterDispose=after_dispose, result=await pending)
        controller.abort('cancel')
        return dict(result=await pending, late=registry.resolveClientQuery(OWNER, request_id, dict(ok=True, data=dict(value=1))), events=events, acks=acks)
    finally:
        await ctx.fiber.dispose()


async def observe(spec):
    mode = spec['mode']
    if spec['kind'] == 'schema':
        validator = assert_object_json_schema if spec.get('objectRoot') else assert_supported_json_schema
        return dict(mode=mode, result=await attempt(lambda: validator(recipe(spec, True))))
    if spec['kind'] == 'value':
        return dict(mode=mode, violations=validate_json_schema_value(spec['schema'], recipe(spec, False), spec.get('path', 'value')))
    if spec['kind'] == 'forged':
        return dict(mode=mode, result=await attempt(lambda: validate_json_schema_value(spec['schema'], spec['value'])))
    if spec['kind'] == 'registry':
        return dict(mode=mode, **await registry_observation(spec))
    ctx = Context()
    ctx.provide('tools', SimpleNamespace(schemas=lambda agent: [dict(name=agent.id, parameters=EMPTY)]))
    try:
        registry = CordisInspectRegistryService(ctx)
        for provider in host_inspect_providers(ctx):
            if provider['manifest']['id'] != 'Builtin':
                registry.register(provider)
        return dict(mode=mode, directory=registry.list(), services=[query_service_api()] + [query_service_api(row['key']) for row in SERVICE_API],
            events=[query_event_api(events=HOST_EVENTS)] + [query_event_api(row['name']) for row in HOST_EVENTS],
            missingService=await attempt(lambda: query_service_api('missing')), missingEvent=await attempt(lambda: query_event_api('missing')),
            tools=await registry.query('host', 'Tool', 'listTools', UNDEFINED, OWNER, NEVER_ABORTED))
    finally:
        await ctx.fiber.dispose()


async def main():
    specs = json.loads((ROOT / 'scripts/oracles/inspect-cases.json').read_text(encoding='utf-8'))
    rows = [await observe(spec) for spec in specs]
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
