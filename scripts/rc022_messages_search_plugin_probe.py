"""Live canonical Messages search composition against the fixed upstream plugin."""
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_messages_search_probe import ANSWER


def cases():
    rows = [dict(auth=auth, current=current, ready=ready, config=config)
            for auth in ('none', 'key', 'account', 'both', 'store', 'store-error', 'account-error')
            for current in (None, 'deepseek-account', 'deepseek-official')
            for ready in (None, 'deepseek-account', 'deepseek-official')
            for config in ('default', 'literal', 'custom')]
    rows.append(dict(auth='key', current=None, ready=None, config='default', live=True))
    return rows


def prepare(output):
    path = output/'inputs.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.environment import DSH_LAUNCH_ENVIRONMENT_KEY, LaunchEnvironmentSnapshot
    from dsh.cordis.volatile import WRITE
    from dsh.web.web_service_current import CurrentWebService
    from dsh.web import messages_search_current as search
    rows = []
    original = search.fetchResponse
    try:
        for index, entry in enumerate(cases()):
            ctx = Context(); events = []; sent = []; changes = []; live = {}
            auth = entry['auth']
            environment = dict(DEEPSEEK_BASE_URL='https://chat-must-ignore.test', DEEPSEEK_SEARCH_BASE_URL='https://environment.test/v1')
            if auth in ('key', 'both', 'account-error'): environment.update(DEEPSEEK_API_KEY='environment-key', OWN_KEY='own-key')
            ctx.set_service(DSH_LAUNCH_ENVIRONMENT_KEY, LaunchEnvironmentSnapshot([dict(source='process', values=environment)]))
            async def token(endpoint):
                events.append('account:'+endpoint)
                if auth == 'account-error': raise RuntimeError('account-read-failed')
                return 'account-token' if auth in ('account', 'both') else None
            ctx.set_service('deepseekAccount', SimpleNamespace(resolveToken=token))
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
            session = SimpleNamespace(requestContext=lambda: dict(provider=entry['current']), append=lambda name, data: events.append(dict(name=name, data=data)))
            ctx.set_service('agents', SimpleNamespace(currentInitiator=lambda: SimpleNamespace(session=session) if entry['current'] is not None else None))
            ctx.on('web/providers-changed', lambda: changes.append('changed'))
            @asynccontextmanager
            async def response(endpoint, headers, body, signal):
                sent.append(dict(endpoint=endpoint, key=headers.get('x-api-key'), authorization=headers.get('authorization'), token=headers.get('x-dsh-auth-token'), body=json.loads(body)))
                async def chunks(): yield json.dumps(ANSWER).encode('utf-8')
                yield dict(status=200), chunks()
            search.fetchResponse = response
            class Capture(search.CurrentWebSearchDeepSeek):
                def apply(self, owner):
                    live.update(self.config)
                    return super().apply(owner)
            try:
                await ctx.plugin(CurrentWebService, dict(searchProvider='deepseek-official'))
                config = dict(apiKey='literal-key') if entry['config'] == 'literal' else {}
                if entry['config'] == 'custom': config.update(baseURL='https://custom.test/path/', apiKeyEnv='OWN_KEY')
                fork = await ctx.plugin(Capture, config)
                async def run():
                    ready = await ctx.web.searchReady(entry['ready'])
                    boundary = len(events)
                    try: result = dict(value=await ctx.web.search(dict(query='fixture')))
                    except Exception as error: result = dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))
                    return dict(ready=ready, readinessEvents=boundary, result=result)
                result = [await run()]
                if entry.get('live'):
                    for key, value in dict(apiKey='updated-key', apiKeyEnv='OWN_KEY', baseURL='https://updated.test/v2', model='updated-model', apiVersion='updated-version', maxTokens=19, maxUses=2).items(): getattr(live[key], WRITE)(value)
                    result.append(await run())
                await fork.dispose()
                rows.append(dict(index=index, result=result, sent=sent, events=events, changes=len(changes), afterDispose=ctx.web.listProviders()))
            finally: await ctx.fiber.dispose()
        return rows
    finally: search.fetchResponse = original


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_messages_search_plugin.mts', 'Actual Messages search plugin: route-specific readiness, credential dispatch, live Config and disposal.',
               [Path(__file__).resolve(), ROOT/'dsh/web/messages_search_current.py', ROOT/'dsh/web/web_service_current.py'], prepare=prepare)
