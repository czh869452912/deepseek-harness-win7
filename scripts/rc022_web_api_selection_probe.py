"""Live route ownership and operation billing through the actual Web registry."""
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def routeRows(mode):
    rows = [] if mode == 'none' else [dict(provider='deepseek-official', config=dict(baseURL='https://key.test/anthropic/path', apiKeyEnv='ROUTE_KEY')),
                                      dict(provider='deepseek-account', config=dict(baseURL='https://account.test/anthropic/path'))]
    if mode == 'invalid-key-route': rows[0]['config']['baseURL'] = 'not a url'
    if mode == 'invalid-account-route': rows[1]['config']['baseURL'] = 'not a url'
    if mode == 'inactive-account': rows[1]['state'] = 0
    if mode == 'foreign-account': rows[1]['name'] = '@fixture/other'
    if mode == 'nested-account': rows[1]['settingsPath'] = ['nested']
    return rows


def cases():
    rows = []
    for capability in ('search', 'fetch'):
        for billing in ('auto', 'account', 'api-key'):
            for provider in (None, 'deepseek-account', 'deepseek-official', 'other'):
                for auth in ('none', 'key', 'account', 'both'):
                    for routes in ('none', 'both', 'invalid-key-route', 'invalid-account-route'):
                        rows.append(dict(capability=capability, billing=billing, provider=provider, auth=auth, routes=routes))
        for routes in ('inactive-account', 'foreign-account', 'nested-account'):
            for provider in ('deepseek-account', 'other'):
                rows.append(dict(capability=capability, billing='auto', provider=provider, auth='both', routes=routes))
        for base in (None, '', 'https://own.test/prefix///', 'not a url'):
            for ref in (None, '', 'OWN_KEY', 'bad-ref'):
                rows.append(dict(capability=capability, billing='account', provider='deepseek-account', auth='both', routes='invalid-key-route', base=base, ref=ref))
        for auth in ('store', 'store-error', 'invalid-key', 'account-error'):
            for provider in (None, 'deepseek-account'):
                rows.append(dict(capability=capability, billing='auto', provider=provider, auth=auth, routes='both'))
        for environment in ('https://environment.test/custom/path', 'not a url'):
            for billing in ('auto', 'account', 'api-key'):
                rows.append(dict(capability=capability, billing=billing, provider=None, auth='both', routes='none', environment=environment))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.environment import DSH_LAUNCH_ENVIRONMENT_KEY, LaunchEnvironmentSnapshot
    from dsh.llm.deepseek_route_config import routeSchema
    from dsh.web.web_service_current import CurrentWebService
    from dsh.web.web_deepseek_api_current import CurrentWebDeepSeekApi, ROUTE_PACKAGES
    from dsh.web import deepseek_api_transport as transport
    rows = []; original = transport.fetchResponse
    try:
        for index, entry in enumerate(cases()):
            ctx = Context(); events = []; sent = []; changes = []; capability = entry['capability']; auth = entry['auth']
            environment = dict(DEEPSEEK_API_KEY='environment-key', ROUTE_KEY='route-key', OWN_KEY='own-key') if auth in ('key', 'both', 'account-error') else {}
            if auth == 'invalid-key': environment = dict(DEEPSEEK_API_KEY='invalid\nkey', ROUTE_KEY='invalid\nkey')
            if 'environment' in entry: environment['DEEPSEEK_BASE_URL'] = entry['environment']
            ctx.set_service(DSH_LAUNCH_ENVIRONMENT_KEY, LaunchEnvironmentSnapshot([dict(source='process', values=environment)]))
            async def token(endpoint):
                events.append('account:'+endpoint)
                if auth == 'account-error': raise RuntimeError('account-read-failed')
                return 'account-token' if auth in ('account', 'both', 'account-error') else None
            async def reject(token): events.append('reject:'+token)
            ctx.set_service('deepseekAccount', SimpleNamespace(resolveToken=token, rejectToken=reject))
            if auth in ('store', 'store-error'):
                async def resolve(ref):
                    events.append('resolve:'+ref)
                    if auth == 'store-error': raise RuntimeError('store-failed')
                    return dict(value='stored-key')
                async def describe(ref):
                    events.append('describe:'+ref)
                    if auth == 'store-error': raise RuntimeError('store-failed')
                    return dict(configured=True)
                ctx.set_service('credentials', SimpleNamespace(resolve=resolve, describe=describe))
            routes = routeRows(entry['routes']); entries = []
            for position, route in enumerate(routes):
                parsed = routeSchema('apiKey' if route['provider'] == 'deepseek-official' else 'account').validate(route['config'])
                assert not parsed.get('issues'), parsed
                entries.append(SimpleNamespace(options=dict(id='route-'+str(position), name=route.get('name', ROUTE_PACKAGES[route['provider']])),
                    fiber=SimpleNamespace(state=route.get('state', 2), effectiveConfig=parsed['value'])))
            ctx.set_service('llm', SimpleNamespace(listProviders=lambda: [dict(id=route['provider']) for route in routes],
                listConfigurableProviders=lambda: [dict(provider=route['provider'], settingsNs='route-'+str(position), settingsPath=route.get('settingsPath', [])) for position, route in enumerate(routes)]))
            ctx.set_service('loader', SimpleNamespace(entries=lambda: iter(entries)))
            session = SimpleNamespace(requestContext=lambda: dict(provider=entry['provider']), deriveMessages=lambda: [
                dict(role='user', source=dict(kind='user'), content=[dict(type='text', text='first question')]),
                dict(role='user', source=dict(kind='injected'), content=[dict(type='text', text='must not send')])])
            ctx.set_service('agents', SimpleNamespace(currentInitiator=lambda: SimpleNamespace(session=session) if entry['provider'] is not None else None))
            ctx.on('web/providers-changed', lambda: changes.append('changed'))
            @asynccontextmanager
            async def response(endpoint, headers, body, signal):
                sent.append(dict(endpoint=endpoint, authorization=headers.get('authorization'), token=headers.get('x-dsh-auth-token'), body=json.loads(body)))
                async def chunks(): yield json.dumps(dict(results=[]) if capability == 'search' else dict(content='# Page')).encode('utf-8')
                yield dict(status=200), chunks()
            transport.fetchResponse = response
            try:
                await ctx.plugin(CurrentWebService, dict(searchProvider='deepseek-search-api', fetchProvider='deepseek-fetch-api'))
                config = {capability+'Billing': entry['billing'], 'apiKey': 'legacy-must-ignore', 'baseURL': 'https://legacy.invalid'}
                if entry.get('base') is not None: config[capability+'BaseURL'] = entry['base']
                if entry.get('ref') is not None: config[capability+'ApiKeyEnv'] = entry['ref']
                fork = await ctx.plugin(CurrentWebDeepSeekApi, config)
                ready = await getattr(ctx.web, capability+'Ready')(entry['provider'])
                try:
                    result = dict(value=await getattr(ctx.web, capability)(dict(query='fixture') if capability == 'search' else dict(url='https://page.test')))
                except Exception as error: result = dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))
                await fork.dispose()
                rows.append(dict(index=index, ready=ready, result=result, sent=sent, events=events, changes=len(changes), afterDispose=ctx.web.listProviders()))
            finally: await ctx.fiber.dispose()
        return rows
    finally: transport.fetchResponse = original


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_web_api_selection.mts', 'Actual Web registry and API plugin: live model-route ownership, billing, custom endpoints and readiness.',
               [Path(__file__).resolve(), ROOT/'dsh/web/web_deepseek_api_current.py', ROOT/'dsh/web/web_service_current.py'], prepare=prepare)
