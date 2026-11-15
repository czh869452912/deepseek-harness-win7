"""Pair V4 factory journeys over actual plain and Zstandard JSONL backends."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None

def prepare(output):
    global OUTPUT
    OUTPUT=output/'files';OUTPUT.mkdir()
    config=output/'workspace.json';config.write_text(json.dumps(str(OUTPUT)),encoding='utf-8');return [config]

async def observe(workspace):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    async def mount(root,compression):
        ctx=Context()
        for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(root),compression=compression))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]));return ctx
    def clean(events):
        def data(event):
            if event['type']!='agent/inbox/spliced':return event['data']
            result=dict(event['data'])
            result['inserted']=[{key:value for key,value in message.items() if key!='id'} for message in result['inserted']]
            return result
        return [dict(type=event['type'],seq=event['seq'],data=data(event),**(dict(surfaceOp=event['surfaceOp']) if 'surfaceOp' in event else {})) for event in events]
    async def read(backend,row=None):
        reader=await backend.open('saved','read')
        try:
            if row is not None:row['inherited']=reader.inheritedEventCount
            return (await reader.read())['events']
        finally:await reader.close()
    rows=[]
    for compression in ('none','zstd'):
        for action in ('empty','seed-setup','inherited','setup-fail','commit-fail','created-fail','queued-fail','resume'):
            root=workspace/(compression+'-'+action);ctx=await mount(root,compression);row=dict(action=action,compression=compression);handles=[];primary=RuntimeError('primary')
            backend=ctx.get('sessionPersistence');agents=ctx.get('agents');sessions=ctx.get('sessions')
            seed=[dict(type='turn/start',seq=0,time=1,data=dict(turn=1)),dict(type='turn/end',seq=1,time=2,data=dict(turn=1,reason=dict(kind='completed')))]
            try:
                if action=='resume':
                    session=sessions.prepare('saved');writer=await backend.create(session.header);await writer.append(seed[:1]);await writer.close()
                def fail():raise primary
                async def setup(scope,agent):
                    row['live']=sessions.get('saved') is agent.session and agents.get('saved') is None
                    row['before']=clean(await read(backend)) if action!='empty' else []
                    if action!='empty':agent.session.append('session/title',dict(title='from setup',messageSeqs=[],source=dict(kind='user')))
                    if action=='queued-fail':agent.followup(message('retained input'))
                    if action in ('setup-fail','queued-fail'):raise primary
                    if action=='commit-fail':return SimpleNamespace(commit=fail)
                async def created(payload):
                    if action=='created-fail':raise primary
                ctx.on('agent/created',created)
                try:
                    request=dict(sessionId='saved',seed=None if action=='empty' else seed,setup=setup)
                    if action=='inherited':request.update(meta=dict(isSeeded=True),inheritedEventCount=2)
                    handle=await (agents.resume(dict(resumeSessionId='saved',setup=setup)) if action=='resume' else agents.create(request))
                    handles.append(handle);await handle.dispose()
                except Exception as error:row['same']=error is primary
                after=await backend.stat('saved');row['exists']=after is not None;row['closed']=not backend.tracker.writers
                if after is not None:
                    row['version']=after['header']['version'];row['stored']=clean(await read(backend,row))
                row['removed']=not sessions.list() and not agents.list()
                if action=='seed-setup':
                    await ctx.fiber.dispose();ctx=await mount(root,compression);backend=ctx.get('sessionPersistence');handle=await ctx.get('agents').resume(dict(resumeSessionId='saved'));handles=[handle]
                    row['cold']=clean(handle.agent.session.snapshotEvents());await handle.dispose();row['coldStored']=clean(await read(backend))
                rows.append(json.loads(json.dumps(row)))
            finally:
                if handles:await asyncio.gather(*(handle.dispose() for handle in handles),return_exceptions=True)
                await ctx.fiber.dispose()
    return rows

async def native():return await observe(OUTPUT/'native')

if __name__=='__main__':
    probe.native=native
    probe.main('rc022_factory_storage.mts','Actual V4 JSONL plain/zstd factory create/seed/setup/commit/announcement failure, retained queued input, interrupted resume repair and cold reopening.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_loop_current.py',ROOT/'dsh/core/agent_lifecycle_current.py',ROOT/'dsh/session/jsonl_backend_current.py'],prepare=prepare)
