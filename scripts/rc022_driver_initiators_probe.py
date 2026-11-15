"""Observe initiators through actual V4 Agent drivers and LLM continuations."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('overlap','clear','child'):
        ctx=Context();handles=[];observations=[];row=dict(action=action);starts=[];both=asyncio.Event();child=[]
        class Adapter(ScriptAdapter):
            async def stream(self,request):
                agents=ctx.get('agents');before=agents.requireInitiator();entry=dict(id=before.id)
                starts.append(before.id)
                if action=='overlap':
                    if len(starts)==2:both.set()
                    await both.wait()
                if action=='clear':
                    async def cleared():await asyncio.sleep(0);return agents.currentInitiator()
                    entry['cleared']=await agents.withoutInitiator(cleared) is None
                if action=='child' and before.id=='parent':
                    def setup(scope,subject):row.update(setupParent=agents.requireInitiator().id,setupChild=subject.id)
                    handle=await agents.create(dict(sessionId='child',agentOptions=dict(provider='script',model='model'),setup=setup));handles.append(handle);child.append(handle.agent);handle.agent.followup(message('child input'))
                await asyncio.sleep(0);entry['after']=agents.requireInitiator() is before;observations.append(entry)
                async for chunk in super().stream(request):yield chunk
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]));ctx.get('llm').registerAdapter(['script'],Adapter(dict(script=[response() for _ in range(4)])))
            agents=ctx.get('agents')
            for sid in (('left','right') if action=='overlap' else ('parent',)):
                handle=await agents.create(dict(sessionId=sid,agentOptions=dict(provider='script',model='model')));handles.append(handle)
            for handle in list(handles):handle.agent.followup(message(handle.agent.id+' input'))
            await asyncio.wait_for(asyncio.gather(*(handle.agent.whenIdle() for handle in list(handles))),4)
            for agent in child:await asyncio.wait_for(agent.whenIdle(),4)
            row['observations']=sorted(observations,key=lambda entry:entry['id']);row['outside']=agents.currentInitiator() is None
            row['idle']=all(handle.agent.status=='idle' for handle in handles);rows.append(row)
        finally:
            both.set()
            for handle in reversed(handles):await handle.dispose()
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_driver_initiators.mts','Real V4 drivers retain exact registry-local initiators through overlapping model streams, clearing boundaries and parent-triggered child setup/driver continuations.',[Path(__file__).resolve(),ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/core/agent_current.py'])
