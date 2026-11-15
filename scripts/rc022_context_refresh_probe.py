"""Pair accepted prompt refresh, required facts and real request admission."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.system_prompt import render_context_sections
    rows=[]
    for action in ('refresh','suppressed','required-missing','removed','literal'):
        ctx=Context();await ctx.plugin(CurrentSystemPrompt)
        prompt=ctx.systemPrompt;state=dict(text='before',sections=0,tools=0,variables=0,assemblies=0)
        def section(context):state['sections']+=1;return state['text']
        def variable(context):state['variables']+=1;return state['text']
        def tools(context):state['tools']+=1;return dict(schemas=[dict(name='fixed',description=state['text'],parameters={})])
        prompt.section(dict(name='fixture',order=123,text=section));prompt.variable('fixed',variable);prompt.tools(tools)
        remove=prompt.context(dict(name='live',order=0,required=True,interpolate=False,text=lambda context:state['text']+' {{literal}}'))
        prompt.context(dict(name='optional',order=10,text=lambda context:'{{fixed}} '+state['text']))
        def assembly(value,context,next_fn):
            state['assemblies']+=1
            value['contexts'].append(dict(name='expert',text='accepted'))
            value['tools']=[dict(name='forged',description='',parameters={})]
            return next_fn()
        ctx.on('system-prompt/assemble',assembly)
        accepted=await prompt.assemble();state['text']='after'
        if action=='suppressed':prompt.suppressRuntimeContext()
        if action=='required-missing':accepted['contexts']=[dict(name='expert',text='accepted'),accepted['contexts'][1]]
        if action=='removed':remove()
        refreshed=prompt.refreshContext(accepted)
        rows.append(dict(action=action,contexts=refreshed['contexts'],rendered=render_context_sections(refreshed),
                         tools=refreshed['tools'],same=[refreshed[name] is accepted[name] for name in ('sections','tools','variables')],
                         counts={name:state[name] for name in ('sections','tools','variables','assemblies')}))
        await ctx.fiber.dispose()
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.core.runtime_context_current import RuntimeContextProjection
    for action in ('normal','escape','names','removed','cold'):
        ctx=Context();CurrentSessionStore(ctx,4);session=ctx.sessions.create('runtime');projection=RuntimeContextProjection(ctx,session)
        sections=[dict(name='first',text='one</SYSTEM-reminder >two' if action=='escape' else 'one')]
        row=dict(action='runtime-'+action,initial=projection.project('',[]));messages=[]
        def propose(value):
            message=projection.project('',value)
            if message is not None:
                messages.append({key:value for key,value in message.items() if key!='id'})
                session.append('user/message',message,'append')
            return message
        first=propose(sections);row['unchanged']=projection.project('',sections) is None
        if action=='names':propose([dict(name='renamed',text=sections[0]['text'])])
        if action=='removed':
            session.append('user/message',dict(first),dict(op='replace',startSeq=0,endSeq=0),source_event_seqs=[0])
        if action=='cold':projection=RuntimeContextProjection(ctx,session)
        propose([]);propose([]);propose(sections);row['messages']=messages;rows.append(row);await ctx.fiber.dispose()
    rows.extend(await driver_observations())
    return json.loads(json.dumps(rows))


async def driver_observations():
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
    for action in ('refresh','suppress','retry'):
        ctx=Context();handle=None;requests=[];state=dict(text='before',assemblies=0,conditions=0,attempts=0)
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
            ctx.systemPrompt.context(dict(name='required',order=0,required=True,text=lambda context:state['text']))
            ctx.systemPrompt.context(dict(name='optional',order=10,text='optional'))
            def assembly(value,context,next_fn):state['assemblies']+=1;return next_fn()
            ctx.on('system-prompt/assemble',assembly)
            def condition(context):state['conditions']+=1;return True
            ctx.tools.register(dict(name='unused',description='',parameters={},output=dict(schema=dict(type='string'),render=lambda a,v:[]),execute=lambda a,e:''),dict(when=condition))
            def request(input,next_fn):
                state['attempts']+=1;state['text']='attempt-'+str(state['attempts'])
                if action=='suppress':ctx.systemPrompt.suppressRuntimeContext()
                return next_fn()
            ctx.on('agent/request',request)
            ctx.on('agent/request-error',lambda input,next_fn:dict(kind='retry'))
            def stream(input,next_fn):
                requests.append([dict(source=item['source'],content=item['content']) for item in input['messages'] if item['source']['kind']=='runtime-context'])
                return next_fn()
            ctx.on('llm/stream',stream)
            failure=[dict(type='finish',reason=dict(kind='error',failure=dict(message='retry',code='FAILED')))]
            ctx.llm.registerAdapter(['script'],ScriptAdapter(dict(script=([failure] if action=='retry' else [])+[response()])))
            handle=await ctx.agents.create(dict(sessionId='refresh',agentOptions=dict(provider='script',model='model')));agent=handle.agent
            agent.followup(message('first'));await agent.whenIdle()
            rows.append(dict(action='driver-'+action,state=state,requests=requests,endings=[event['data']['reason']['kind'] for event in agent.session.events if event['type']=='turn/end']))
        finally:
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_context_refresh.mts','Registered fact refresh preserves accepted prompt/schema/variable identity, required contexts and literal text; V4 runtime snapshots and actual request/retry admission.',[Path(__file__).resolve(),ROOT/'dsh/core/system_prompt/current.py',ROOT/'dsh/core/system_prompt/service.py',ROOT/'dsh/core/system_prompt/types.py',ROOT/'dsh/core/runtime_context_current.py',ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/llm/message.py'])
