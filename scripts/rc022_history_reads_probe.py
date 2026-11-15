"""Pair passive history cuts and header-only cache views with fixed Source."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def normalized(value):
    return json.loads(json.dumps(value), object_hook=lambda item:dict(item, time=0) if 'time' in item and 'seq' in item and 'type' in item else item)


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_history_authorized import SessionHistoryReads
    from dsh.storage.hub import StoragePlugin
    from dsh.storage.plugins import StorageJsonPlugin, StorageDomainPlugin
    from dsh.session.projection_cache_current import HeaderSessionProjectionCachePlugin
    from dsh.core.abort import AbortController
    from dsh.core.session import SessionHeader
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];observed=[]
    original_query=ctx.sessionQuery.observeSession
    async def query(identity, options=None):
        observed.append(options['projectionMode'])
        return await original_query(identity, options)
    ctx.sessionQuery.observeSession=query
    try:
        for plugin,config in [(StoragePlugin,None),(StorageJsonPlugin,dict(root=str((workspace or WORKSPACE)/'native-storage'))),(StorageDomainPlugin,dict(backend='json'))]:
            await ctx.plugin(plugin,config)
        await ctx.sessionProjections.register(dict(key='title', stateVersion=1, stateSchema=str, init=lambda *_:'Title', apply=lambda state,event:state,
            wire=dict(viewSchema=str, view=lambda state:state)))
        await ctx.plugin(HeaderSessionProjectionCachePlugin,dict(writeEveryEvents=1000,writeIntervalMs=60000))
        history=SessionHistoryReads(ctx)
        handle=await ctx.agents.create(dict(sessionId='history',meta=dict(cwd='C:/history'),agentOptions=dict(provider='script',model='model')))
        session=handle.agent.session
        for turn in (1,2,3):
            session.append('turn/start',dict(turn=turn))
            session.append('user/message',dict(id='u'+str(turn),role='user',content=[dict(type='text',text='prompt')],source=dict(kind='user')), 'append')
            session.append('step/start',dict(turn=turn,step=1))
            session.append('assistant/message',dict(turn=turn,step=1,message=dict(id='a'+str(turn),role='assistant',content=[dict(type='text',text='answer')],source=dict(kind='model',provider='script',model='model')),stream=[]), 'append')
            session.append('step/end',dict(turn=turn,step=1))
            session.append('turn/end',dict(turn=turn,reason=dict(kind='completed')))
        address=dict(kind='session',sessionId='history')
        async def read(name, request):
            rows.append(dict(name=name,value=await history.events(dict(address=address,**request),fixture.signal)))
        await read('default-cut',{})
        await read('fixed-cut',dict(throughSeq=11,maxMessages=2))
        await read('older-page',dict(beforeSeq=12,maxMessages=1))
        await read('empty-cut',dict(throughSeq=-1))
        await read('turn-window',dict(maxMessages=6,turnWindow=dict(minMessages=2,minTurns=2)))
        rows.append(dict(name='assistant-output',value=await history.assistantOutput('history',3,17,1,fixture.signal)))
        rows.append(dict(name='assistant-interval',value=await history.assistantOutput('history',9,17,2,fixture.signal)))
        for name,request in [('future-cut',dict(throughSeq=100)),('negative-zero',dict(throughSeq=-0.0)),('bad-window',dict(maxMessages=1,turnWindow=dict(minMessages=2,minTurns=1)))]:
            try: await history.events(dict(address=address,**request),fixture.signal)
            except Exception as error: rows.append(dict(name=name,error=dict(code=error.code,message=error.message)))
        rows.append(dict(name='live-projections',value=await history.projections(dict(sessionId='history'),fixture.signal)))
        await ctx.sessionProjectionCache.write(session)
        rows.append(dict(name='header-cache',value=ctx.sessionProjectionCache.cachedSnapshot(session.header,['title'])))
        await handle.dispose()
        before=len(observed)
        rows.append(dict(name='cold-projections',value=await history.projections(dict(sessionId='history'),fixture.signal),reads=len(observed)-before,agentAbsent=ctx.agents.get('history') is None))
        await read('cold-history',dict(maxMessages=2))
        rows.append(dict(name='missing-projections',value=await history.projections(dict(sessionId='missing'),fixture.signal)))
        try: await history.events(dict(address=dict(kind='subagent',parentSessionId='parent',childSessionId='missing',mode='unknown')),fixture.signal)
        except Exception as error: rows.append(dict(name='missing-subagent',error=dict(code=error.code,details=error.details)))
        cache=ctx.sessionProjectionCache
        header=SessionHeader('seeded-cache',created_at=10,cwd='C:/cache',version=4,is_seeded=True)
        row=dict(identity=dict(formatVersion=4,createdAt=10,cwd='C:/cache',isSeeded=True,inheritedEventCount=7),rows=dict(title=dict(ver=1,seq=9,val='Seeded title')))
        await cache.table.put(header.id,row)
        rows.append(dict(name='seeded-header-cache',value=cache.cachedSnapshot(header),wrongCutSeeds=bool(cache._rows(header,0))))
        replaced=SessionHeader(header.id,created_at=11,cwd='C:/cache',version=4,is_seeded=True)
        rows.append(dict(name='cache-lifecycle-refusal',value=cache.cachedSnapshot(replaced)))
        old=dict(row,identity=dict(row['identity'],formatVersion=3))
        await cache.table.put(header.id,old)
        rows.append(dict(name='predecessor-title',current=cache.cachedSnapshot(header),predecessor=cache.cachedPredecessorTitle(header)))
        persistence=ctx.sessionPersistence
        original_stat=persistence.stat
        async def migration_stat(*_):return dict(header=header,formatStatus='migration-required')
        persistence.stat=migration_stat
        # A current-format cache row is a hint, never a sequenced baseline for migration.
        await cache.table.put(header.id,row)
        before=len(observed)
        rows.append(dict(name='migration-hints',value=await history.projections(dict(sessionId=header.id),fixture.signal),reads=len(observed)-before))
        persistence.stat=original_stat
        aborted=AbortController();aborted.abort()
        try: await history.projections(dict(sessionId='history'),aborted.signal)
        except Exception as error: rows.append(dict(name='projection-aborted',error=dict(code=error.code,message=error.message)))
        rows.append(dict(name='passive',agents=len(ctx.agents.list()),modes=observed))
        return normalized(rows)
    finally: await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_history_reads.mts','Actual Session/Agent/journal/query/projection and JSON storage-domain/cache providers: passive live/cold history cuts, message/turn windows, bounded assistant output, exact projections, header-only seeded cache identity and predecessor title. Migration stat is a controlled collaborator; reads must avoid activation. Passive subscriptions and full controller boot are separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_history_authorized.py',ROOT/'dsh/api/session_authorized.py',ROOT/'dsh/session/projection_cache_current.py'],prepare=prepare)
