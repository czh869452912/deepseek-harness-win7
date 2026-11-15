"""Pair current Session summary handles and header-only persisted hints."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_list_authorized import AuthorizedSessionList
    from dsh.storage.hub import StoragePlugin
    from dsh.storage.plugins import StorageJsonPlugin,StorageDomainPlugin
    from dsh.session.projection_cache_current import HeaderSessionProjectionCachePlugin
    from dsh.core.session import SessionHeader
    from dsh.core.abort import AbortController
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];opens=[]
    limits=dict(maxImageBytes=1,maxImagesPerMessage=1,maxMessageImageBytes=1,maxImagePixels=1,maxImageDimension=1,mediaTypes=['image/png'])
    ctx.set_service('attachments',NS(imageLimits=limits))
    try:
        for plugin,config in [(StoragePlugin,None),(StorageJsonPlugin,dict(root=str((workspace or WORKSPACE)/'native-storage'))),(StorageDomainPlugin,dict(backend='json'))]:await ctx.plugin(plugin,config)
        listing=AuthorizedSessionList(ctx,1);await listing.initialize()
        await ctx.sessionProjections.register(dict(key='title',stateVersion=1,stateSchema=str,init=lambda *_:'Title',apply=lambda state,event:state,wire=dict(viewSchema=str,view=lambda state:state)))
        await ctx.plugin(HeaderSessionProjectionCachePlugin,dict(writeEveryEvents=1000,writeIntervalMs=60000))
        handle=await ctx.agents.create(dict(sessionId='summary',meta=dict(cwd='C:/summary',createdAt=100),agentOptions=dict(provider='script',model='model')));session=handle.agent.session
        rows.append(dict(name='blank-live',value=listing.summaryFor(session)))
        session.append('user/message',dict(id='prompt',role='user',content=[dict(type='text',text='hello')],source=dict(kind='user')),'append')
        rows.append(dict(name='prompt-still-blank',value=listing.summaryFor(session),recency=listing.summaryFor(session)['updatedAt']==session.snapshotEvents()[-1]['time']))
        session.append('turn/start',dict(turn=1));session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        rows.append(dict(name='started-live',value=listing.summaryFor(session)))
        rows.append(dict(name='all-wire',value=ctx.sessionProjections.snapshot(session)))
        await ctx.sessionProjectionCache.write(session)
        await handle.dispose()
        original=ctx.sessionPersistence.open
        async def opened(*args,**kwargs):opens.append(True);return await original(*args,**kwargs)
        ctx.sessionPersistence.open=opened
        rows.append(dict(name='cold-cached-list',value=await listing.list(fixture.signal),opens=len(opens),agents=len(ctx.agents.list())))
        header=SessionHeader('seeded',created_at=10,cwd='C:/seeded',version=4,is_seeded=True)
        await ctx.sessionProjectionCache.table.put('seeded',dict(identity=dict(formatVersion=4,createdAt=10,cwd='C:/seeded',isSeeded=True,inheritedEventCount=7),rows=dict(title=dict(ver=1,seq=9,val='Seeded'),sessionListMetadata=dict(ver=1,seq=7,val=dict(blank=True,lastPromptAt=None)),imageLimits=dict(ver=1,seq=10,val=None))))
        rows.append(dict(name='seeded-header',value=listing._summary(header,format_status='current')))
        rows.append(dict(name='cold-miss',value=listing._summary(SessionHeader('miss',created_at=4,cwd='C:/miss',version=4),format_status='migration-required')))
        live=ctx.sessions.create('attached',meta=dict(createdAt=3,cwd='C:/attached'))
        rows.append(dict(name='attached-no-agent',value=listing.summaryFor(live)))
        def failure(_):raise RuntimeError('view failed')
        await ctx.sessionProjections.register(dict(key='broken',stateVersion=1,stateSchema=str,init=lambda *_:'state',apply=lambda state,event:state,wire=dict(viewSchema=str,view=failure)))
        rows.append(dict(name='wire-failure-keeps-metadata',value=listing.summaryFor(live)))
        abort=AbortController();abort.abort()
        try:await listing.list(abort.signal)
        except Exception as error:rows.append(dict(name='cancelled',nameOfError=error.name))
        def normalize(value):
            if isinstance(value,dict):return {key:(0 if key=='updatedAt' or key=='lastPromptAt' and item is not None else normalize(item)) for key,item in value.items()}
            if isinstance(value,(list,tuple)):return [normalize(item) for item in value]
            return value
        return normalize(json.loads(json.dumps(rows)))
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_summary.mts','Actual Session/Agent/projection-handle/JSONL/storage-domain/header-cache list summaries: live blankness and recency, summary-excluded image limits, exact versus cached hints, seeded header rows, format status, cold cache misses, attached Sessions without Agents, wire failure isolation and cancellation. Cached list reads count actual persistence opens. Seeded and missing cold headers are explicit controlled row inputs; scheduling is separately verified.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_list_authorized.py',ROOT/'dsh/session/query_current.py',ROOT/'dsh/session/projection_cache_current.py'],prepare=prepare)
