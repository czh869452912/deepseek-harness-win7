"""Actual public service journeys across live and cold subagent branches."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
ACTIONS=('live','cold-creator','provider-removed','sender-stale','root-replaced','unreadable','capacity','parent-direct','outside')


async def observe(workspace):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.volatile import WRITE
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
    from dsh.subagent.service import SubagentPlugin
    from dsh.subagent.providers import SpawnInProcessPlugin
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ACTIONS:
        ctx=Context();row=dict(action=action);received=[]
        for plugin in (CurrentLlmRuntime,Store,Projections,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):
            await ctx.plugin(plugin)
        await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(workspace/action),compression='none'))
        await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
        ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=['hang']*30)))
        query=CurrentSessionQueryService(ctx);ctx.set_service('sessionQuery',query)
        async def ensure(agent,signal):return 'C:/rc022-work'
        async def directory(agent,path,signal):return path
        ctx.set_service('workingDirectory',NS(ensure=ensure,set=directory))
        await ctx.plugin(SubagentPlugin,dict(maxActiveSubagents=3))
        provider_owner=await ctx.plugin(SpawnInProcessPlugin)
        service=ctx.get('subagents');manager=service.manager
        parent=(await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))).agent
        async def root_guard(payload,next):return dict(kind='reject') if payload['agent'] is parent else await next()
        ctx.on('agent/pre-step',root_guard)
        async def start(creator,identity):
            receipt=await service.startActivation(dict(provider='spawn',parent=creator,childId=identity,name=identity,label='Task',
                prompt=[dict(type='text',text='TASK:'+identity)],signal=NEVER_ABORTED,delivery='caller'))
            async def running():
                while ctx.agents.get(identity).status!='running':await asyncio.sleep(.001)
            await asyncio.wait_for(running(),3)
            return receipt,ctx.agents.get(identity)
        a,sender=await start(parent,'a');b,branch=await start(parent,'b');leaf,target=await start(branch,'leaf')
        original_get=ctx.agents.get;original_observe=query.observeSession;stale=False
        def inserted(payload):
            message=payload['message'];source=message['source']
            if source['kind']=='agent-message':
                received.append(dict(target=payload['agent'].id,sender=source['senderSessionId'],
                    text=''.join(block['text'] for block in message['content'] if block['type']=='text')))
        ctx.on('agent/inbox/inserted',inserted)
        async def send(who,identity,text):return await service.sendMessage(who,identity,[dict(type='text',text=text)],dict(signal=NEVER_ABORTED))
        try:
            row['names']=[service.namesOf(agent) for agent in (parent,sender,branch,target)]
            if action in ('cold-creator','unreadable'):await b['dispose']()
            if action not in ('live','parent-direct','outside'):await leaf['dispose']()
            if action=='provider-removed':await provider_owner.dispose()
            if action in ('sender-stale','root-replaced','unreadable'):
                async def observe_session(identity,options):
                    nonlocal stale
                    if action=='unreadable' and identity=='leaf':raise RuntimeError('history unavailable')
                    observation=await original_observe(identity,options);stale=True;return observation
                query.observeSession=observe_session
                def get(identity):
                    if stale and identity==('a' if action=='sender-stale' else 'root'):
                        return None if action=='sender-stale' else NS(id='root')
                    return original_get(identity)
                if action!='unreadable':ctx.agents.get=get
            if action=='capacity':
                getattr(service.config['maxActiveSubagents'],WRITE)(2)
                await send(sender,'b','resident')
            if action=='parent-direct':
                await send(target,'b','direct')
                row['omitClosing']=manager.resident['leaf'].omitClosingText
            elif action=='outside':
                outsider=(await ctx.agents.create(dict(sessionId='outside'))).agent
                await send(outsider,'leaf','forbidden')
            else:
                await send(sender,'leaf','cousin')
                if action=='live':
                    await send(parent,'leaf','grandchild');await send(target,'root','grandparent')
                    try:service.interrupt('leaf',dict(kind='ancestor',agent=sender))
                    except Exception as error:row['interrupt']=error.code
                    try:await send(sender,'a','self')
                    except Exception as error:row['self']=error.code
                if action=='cold-creator':
                    row['creatorLive']=ctx.agents.get('b') is not None
                    row['resumedNames']=service.namesOf(ctx.agents.get('leaf'))
                row['accepted']=True
        except Exception as error:row['error']=getattr(error,'code',None)
        finally:
            ctx.agents.get=original_get;query.observeSession=original_observe
            row['received']=list(received)
            row['beforeDrain']=sorted(manager.resident)
            await manager.drain()
            row['resident']=sorted(manager.resident);row['slots']=len(manager.root_pool(parent).slots)
            row['reservations']=len(manager.names.pending)
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
    probe.main('rc022_subagent_siblings.mts','Public service, actual factory/persistence/query live cross-branch relay, cold target-only resume with offline creator, provider removal, stale sender/replaced root reauthorization, unreadable history, capacity and direct-parent omission.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/service.py',ROOT/'dsh/subagent/manager.py',ROOT/'dsh/subagent/lifetime.py'],prepare=prepare)
