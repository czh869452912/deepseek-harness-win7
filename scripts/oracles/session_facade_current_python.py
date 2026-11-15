"""Current complete Session Remote with real journals and controlled external capabilities."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from dsh.api.session_current import CurrentSessionController
from dsh.api.session_catalogs_current import CurrentSessionSkillCatalog
from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.inbox_current import ReactLoopInbox
from dsh.core.session.current_session import CurrentSession, CurrentSessionPlugin
from dsh.core.session.types import validate_session_header
from dsh.session.projections import SessionProjectionsPlugin
from dsh.session.session_query import SessionQueryError
from dsh.typert.current import CurrentTypertRegistry as TypertRegistry
from dsh.typert.remote import RemoteError


async def run(case):
    ctx, controller, calls, results, live, signals = Context(), AbortController(), [], [], {}, []
    resolver, disposed = [], []
    def fail(value):
        if isinstance(value, dict) and 'throw' in value:
            raise ThrownValueError(value['throw'])
        raise RuntimeError(str(value))
    async def observe(sid, options=None):
        calls.append(dict(op='observe', sessionId=sid, **(dict(projectionMode=options['projectionMode']) if options and 'projectionMode' in options else {})))
        if case.get('queryError'):
            if case['queryError'] == 'missing':
                raise SessionQueryError('missing', 'SESSION_QUERY_SESSION_NOT_FOUND')
            fail(case['queryError'])
        header = dict(version=3, id=sid, createdAt=1, isSeeded=False, **case.get('header', dict(cwd='/workspace')))
        return SimpleNamespace(header=validate_session_header(sid, header, expected_version=3), inheritedEventCount=0, events=[],
            cursor=-1, source='live', projections=None if case.get('unprojected') else dict(asOfSeq=-1, values=dict(agentPreset=case.get('preset'))),
            dispose=lambda: disposed.append(sid))
    def register(resolve):
        resolver.append(resolve)
        return lambda: resolver.remove(resolve)
    async def native(path, signal, action):
        calls.append(dict(op=action, path=path, signal=signal is controller.signal))
        if case.get('nativeAbort'):
            controller.abort(RuntimeError('caller cancelled'))
        if 'nativeError' in case:
            fail(case['nativeError'])
    async def models(provider):
        row = next(row for row in case.get('providers', []) if row['id'] == provider)
        if 'error' in row:
            fail(row['error'])
        return row.get('models', [])
    async def info(provider, model):
        row = next(row for row in case['providers'] if row['id'] == provider)
        entry = next(row for row in row['models'] if row['id'] == model)
        if 'resolveError' in entry:
            fail(entry['resolveError'])
        return entry
    async def skills(options, scoped=False):
        scope = options['scope']
        calls.append(dict(op='skills', cwd=options['cwd'], scope='agent' if scope is live.get('one') and scope is not None else 'standing' if scope is standing else None, scoped=scoped))
        if 'skillError' in case:
            fail(case['skillError'])
        return case.get('skills', [])
    standing = object()
    async def standing_key(preset):
        calls.append(dict(op='standing', preset=preset))
        if case.get('standingError'):
            fail('unknown preset')
        return standing
    def service_for(agent, name):
        calls.append(dict(op='serviceFor', agent=agent is live.get('one'), service=name))
        return SimpleNamespace(list=lambda options: skills(options, True)) if case.get('scopedSkills') else None
    with patch.object(CurrentSession, '_event_time', return_value=1000):
        try:
            for plugin in (CurrentSessionPlugin, SessionProjectionsPlugin, TypertRegistry):
                await ctx.plugin(plugin)
            ctx.set_service('agentDefaultModel', SimpleNamespace(currentSelection=lambda: dict(provider='fixture', model='model')))
            ctx.set_service('agents', SimpleNamespace(get=live.get, isOwnedBy=lambda *_: False))
            ctx.set_service('sessionQuery', SimpleNamespace(observeSession=observe))
            ctx.set_service('attachments', SimpleNamespace(imageLimits=dict(maxImageBytes=100,maxImagesPerMessage=2,maxMessageImageBytes=200,maxImagePixels=100,maxImageDimension=10,mediaTypes=['image/png'])))
            ctx.set_service('fileUploads', SimpleNamespace(registerAgentResolver=register))
            ctx.set_service('workspaceRegistry', SimpleNamespace(list=lambda: []))
            ctx.set_service('llm', SimpleNamespace(listProviders=lambda: [{key: row[key] for key in ('id','name')} for row in case.get('providers', [])], listModels=models, resolveModelInfo=info))
            if not case.get('noSkills'):
                ctx.set_service('skills', SimpleNamespace(list=skills))
            if case.get('presets'):
                ctx.set_service('agentPresets', SimpleNamespace(standingKeyFor=standing_key, serviceFor=service_for))
            api = CurrentSessionController(ctx, case.get('config'), dict(openPath=lambda path, signal: native(path, signal, 'open'), revealPath=lambda path, signal: native(path, signal, 'reveal')))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            if case.get('live'):
                class Agent:
                    pass
                agent=Agent(); agent.id, agent.status, agent.ctx='one','idle',ctx
                agent.session=ctx.get('sessions').create('one', dict(meta=dict(createdAt=1,cwd='/workspace')))
                agent.inbox=ReactLoopInbox(ctx.get('sessionProjections'), agent.session, SimpleNamespace(emit=lambda *_: None))
                live['one']=agent
            if case.get('aborted'):
                controller.abort(RuntimeError('caller cancelled'))
            for action in case['actions']:
                try:
                    op=action['op']
                    if op=='catalog': value=await api.modelCatalog()
                    elif op=='skills': value=await ctx.get('sessionSkillCatalog').list(dict(sessionId='one'),controller.signal)
                    elif op=='available': value=api.canOpenWorkspacePath()
                    elif op=='open': value=await api.openWorkspacePath(action['request'], controller.signal)
                    elif op=='inspect':
                        found=await api.inspect('one',controller.signal); value=dict(meta=dict(found['meta']),events=found['events'],inheritedEventCount=found['inheritedEventCount'])
                    elif op=='resolver':
                        found=await resolver[0]('one'); value=dict(id=found.id, exact=found is live.get('one'))
                    elif op=='prompt': value=await api.prompt(dict(sessionId='one',input=dict(text='should not admit')),controller.signal)
                    else: raise RuntimeError('unknown operation '+op)
                    results.append(dict(outcome='value',value=value))
                except Exception as error:
                    results.append(dict(outcome='error',error=dict(message=str(error),**(dict(code=error.code,details=error.details) if isinstance(error,RemoteError) else {}))))
            return dict(results=results,calls=calls,disposed=disposed)
        finally:
            await ctx.fiber.dispose()
            assert not resolver


def execute(case):
    return json.loads(json.dumps(asyncio.run(run(case))))
