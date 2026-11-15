"""Pair admission ownership through real factory/driver/model/tool consumers."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('enabled','disabled','reject','empty','condition-failure','request-failure','model-later'):
        ctx=Context();handle=None;sets=[];choices=[];requests=[];bodies=[];errors=[];primary=RuntimeError('primary')
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
            original=ctx.tools.resolve
            async def resolve(context):
                value=await original(context);sets.append(value);return value
            ctx.tools.resolve=resolve
            async def condition(context):
                choices.append(dict(context['modelSelection']));await asyncio.sleep(0)
                if action=='condition-failure':raise primary
                return action!='disabled' and context['modelSelection']['model']=='initial'
            async def execute(args,execution):
                bodies.append(execution.toolSet is sets[0]);execution.concludeTurn();return 'done'
            definition=dict(name='work',description='',parameters=dict(type='object'),output=dict(schema=dict(type='string'),render=lambda a,v:[dict(type='text',text=v)]),execute=execute)
            ctx.tools.register(definition,dict(when=condition));ctx.tools.register(dict(definition,name='plain'))
            async def before(input,next_fn):
                if action=='reject':return dict(kind='reject')
                if action=='empty':return dict(kind='enter',messages=[])
                if action=='model-later':input['agent'].model.select(dict(provider='script',model='later'))
                return await next_fn()
            ctx.on('agent/pre-step',before)
            def request(input,next_fn):
                if action=='request-failure':raise primary
                return next_fn()
            ctx.on('agent/request',request)
            ctx.on('agent/error',lambda input:errors.append(dict(primary=input['error'] is primary,code=getattr(input['error'],'code',None))))
            ctx.on('llm/stream',lambda input,next_fn:(requests.append(dict(model=input['model'],tools=[item['name'] for item in input['tools']])),next_fn())[1])
            calls=[dict(type='block-start',index=0,blockType='tool-call'),dict(type='tool-call-delta',index=0,id='call',name='work',argumentsDelta='{}'),dict(type='block-end',index=0,block=dict(type='tool-call',id='call',name='work',arguments='{}')),dict(type='finish',reason=dict(kind='tool-calls'))]
            ctx.llm.registerAdapter(['script'],ScriptAdapter(dict(script=[calls,response()])))
            handle=await ctx.agents.create(dict(sessionId='step',agentOptions=dict(provider='script',model='initial')))
            agent=handle.agent;agent.followup(message('first'));await agent.whenIdle()
            if action=='model-later':agent.followup(message('second'));await agent.whenIdle()
            events=agent.session.snapshotEvents()
            rows.append(dict(action=action,choices=choices,requests=requests,bodies=bodies,errors=errors,
                             closed=all(not value.view(agent) for value in sets),sets=len(sets),
                             results=[event['data']['error']['code'] if event['data'].get('error') else event['data']['message']['content'][0]['text'] for event in events if event['type']=='tool/result'],
                             endings=[event['data']['reason']['kind'] for event in events if event['type']=='turn/end']))
        finally:
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_step_admission.mts','Actual V4 Agent step admission lifecycle, fixed selection, declared tools and batch execution, reject/empty/failure disposal, later model choices.',[Path(__file__).resolve(),ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/core/tools.py',ROOT/'dsh/core/tool_calls.py'])
