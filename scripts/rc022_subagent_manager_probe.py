"""Exercise the unified manager with actual v4 factory, storage and query."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.subagent.manager import SubagentManager
    from dsh.subagent.catalog import CATALOG
    from dsh.subagent.projections import IDENTITY,TIMING4
    from dsh.subagent.in_process import InProcessProvider
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('fresh','fork','resume','prepare-failure','catalog-failure','directory-failure','capacity','external'):
        ctx=Context();manager=None;edges=[];captured=[]
        for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):
            await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(workspace/action),compression='none'))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=[response('answer') for _ in range(5)])))
        catalog=await ctx.sessionProjections.register(CATALOG)
        identity=await ctx.sessionProjections.register(IDENTITY)
        await ctx.sessionProjections.register(TIMING4)
        ctx.set_service('sessionQuery',CurrentSessionQueryService(ctx))
        async def ensure(agent,signal):signal.throwIfAborted();return 'C:/rc022-work'
        async def directory(agent,path,signal):
            signal.throwIfAborted()
            if action=='directory-failure':raise RuntimeError('directory failed')
            return path
        ctx.set_service('workingDirectory',NS(ensure=ensure,set=directory))
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        def emit(event,info,root):
            edges.append(dict(event=event,id=info['id'],local=info['local'],**(dict(stopReason=info['stopReason']) if 'stopReason' in info else {})))
            if event=='subagent/start' and info['local']:
                child=ctx.agents.get(info['id'])
                captured.append(dict(published=child is not None,own=child.session.isOwnSeq(identity.stateOf(child.session)['identity']['seq']),
                    inherited=child.session.inheritedEventCount))
        manager=SubagentManager(ctx,NS(identityOf=lambda session:identity.stateOf(session).get('identity'),
            catalogOf=lambda session:CATALOG['wire']['view'](catalog.stateOf(session)),emitLifecycle=emit),lambda:1)
        row=dict(action=action)
        original=parent.session.append
        held=None
        try:
            if action=='fork':
                parent.session.append('turn/start',dict(turn=1));parent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
                parent.session.append('turn/start',dict(turn=2))
            provider=InProcessProvider('local',action=='fork')
            async def prepare(request):
                if action=='prepare-failure':raise RuntimeError('prepare failed')
                return await provider.prepareContinuable(request)
            if action=='catalog-failure':
                def append(kind,*args,**kwargs):
                    if kind=='subagent/catalog':raise RuntimeError('catalog failed')
                    return original(kind,*args,**kwargs)
                parent.session.append=append
            if action=='capacity':held=manager.root_pool(parent).reserve(1)
            spec=dict(provider='local',parent=parent,childId='child',name='worker',label='Task',
                      prompt=[dict(type='text',text='task')],signal=NEVER_ABORTED,delivery='caller')
            if action=='external':
                completion=asyncio.get_running_loop().create_future()
                async def dispose():pass
                async def external(request):return NS(id='external',result=completion,dispose=dispose)
                receipt=await manager.start_external(dict(spec,delivery='parent'),external)
                completion.set_result(dict(output=[dict(type='text',text='remote')],stopReason='completed'))
            else:
                receipt=await manager.start_local(spec,prepare)
            row['receipt']=dict(childId=receipt['childId'],name=receipt['name'],message='messageId' in receipt)
            row['result']=await asyncio.wait_for(asyncio.shield(receipt['result']),5)
            if action=='resume':
                assert ctx.agents.get('child') is None
                row['resolved']=await manager.resolve_name(parent,'worker')
                await manager.send_message(parent,'child',[dict(type='text',text='again')],dict(signal=NEVER_ABORTED))
                await asyncio.wait_for(manager.wait_for_tree_work(parent),5)
            if action!='external':
                observation=await ctx.get('sessionQuery').observeSession('child',{})
                try:
                    row['descriptors']=[dict(event['data']) for event in observation.events if event['type']=='subagent/descriptor']
                    row['turns']=[event['data']['reason']['kind'] for event in observation.events if event['type']=='turn/end']
                finally:observation.dispose()
        except Exception as error:
            row['error']=getattr(error,'code',None)
        finally:
            parent.session.append=original
            if held is not None:held()
            await manager.drain()
            row['catalog']=[{key:entry[key] for key in ('id','name','mode','label') if key in entry} for entry in CATALOG['wire']['view'](catalog.stateOf(parent.session))]
            row.update(edges=edges,captured=captured,resident=list(manager.resident),childLive=ctx.agents.get('child') is not None,
                reservations=len(manager.names.pending),slots=len(manager.root_pool(parent).slots))
            await ctx.fiber.dispose()
        rows.append(row)
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8')
    return [path]


if __name__=='__main__':
    probe.native=lambda:observe(WORKSPACE/'native')
    probe.main('rc022_subagent_manager.mts','Actual v4 factory/storage/query local and fork creation, cold target resume, catalog/inbox rollback, capacity rejection, directory and preparation failures, external settlement.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/manager.py',ROOT/'dsh/subagent/lifetime.py',ROOT/'dsh/subagent/child_agent.py'],prepare=prepare)
