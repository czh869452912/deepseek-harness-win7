"""Pair V4 pending-call recovery and real failed Agent steps."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(action=action,cause=cause) for cause in ('interrupted','forked')
            for action in ('empty','pending','matched','wrong-step','replacement','closed-step','closed-turn','extra-event')]


def events_for(action):
    if action=='empty':return []
    rows=[('turn/start',dict(turn=1)),('step/start',dict(turn=1,step=1)),
          ('assistant/message',dict(turn=1,step=1,message=dict(content=[dict(type='tool-call',id='a'),dict(type='tool-call',id='b')]))),
          ('tool/call',dict(turn=1,step=1,callId='a'))]
    if action in ('matched','wrong-step','replacement'):
        rows.append(('tool/result',dict(turn=1,step=9 if action=='wrong-step' else 1,message=dict(source=dict(callId='a')))))
    if action=='closed-step':rows.append(('step/end',dict(turn=1,step=1)))
    if action=='closed-turn':rows.append(('turn/end',dict(turn=1,reason=dict(kind='completed'))))
    if action=='extra-event':rows.append(('extra/fact',dict(value=1)))
    events=[dict(type=kind,data=data,seq=index,time=100+index) for index,(kind,data) in enumerate(rows)]
    if action in ('matched','wrong-step','replacement'):events[-1]['surfaceOp']='append' if action!='replacement' else dict(op='replace',startSeq=2,endSeq=2)
    return events


async def observe():
    from dsh.core.session.repair import ToolCallRecovery,open_turn_closers
    rows=[]
    for test in cases():
        events=events_for(test['action']);recovery=ToolCallRecovery(dict(kind=test['cause']))
        for event in events:recovery.observe(event)
        a=recovery.results();b=recovery.results()
        rows.append(dict(test=test,results=a,repeat=a==b,closers=open_turn_closers(events,dict(kind=test['cause']))))
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
    from dsh.core.tool_executor_native import NativeToolExecutor
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('executor-unloaded','write-failure','recovery-failure'):
        ctx=Context();handle=None;primary=RuntimeError('primary');secondary=RuntimeError('secondary');failures=[];bodies=[]
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,CurrentToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            dispose=ctx.tools.setExecutor(NativeToolExecutor(ctx));await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
            async def body(args,execution):bodies.append(execution.callId);return 'ok'
            ctx.tools.register(dict(name='work',description='',parameters={},output=dict(schema=dict(type='string'),render=lambda a,v:[dict(type='text',text=v)]),execute=body))
            if action=='executor-unloaded':ctx.on('llm/stream',lambda request,next_fn:(dispose(),next_fn())[1])
            ctx.on('agent/error',lambda input:failures.append(dict(primary=input['error'] is primary,aggregate=[error is primary or error is secondary for error in getattr(input['error'],'errors',[])],cause=getattr(input['error'],'cause',None) is primary)))
            chunks=[]
            for index in range(2):
                block=dict(type='tool-call',id='c'+str(index),name='work',arguments='{}')
                chunks.extend([dict(type='block-start',index=index,blockType='tool-call'),dict(type='tool-call-delta',index=index,id=block['id'],name='work',argumentsDelta='{}'),dict(type='block-end',index=index,block=block)])
            chunks.append(dict(type='finish',reason=dict(kind='tool-calls')))
            ctx.llm.registerAdapter(['script'],ScriptAdapter(dict(script=[chunks])))
            handle=await ctx.agents.create(dict(sessionId='recover',agentOptions=dict(provider='script',model='model')));agent=handle.agent
            if action!='executor-unloaded':
                append=agent.session.append
                def checked(kind,data,*args,**kwargs):
                    if kind=='tool/result':
                        if data.get('error') and action=='recovery-failure':raise secondary
                        if not data.get('error'):raise primary
                    return append(kind,data,*args,**kwargs)
                agent.session.append=checked
            agent.followup(message('go'));await agent.whenIdle();events=agent.session.events
            rows.append(dict(action=action,bodies=bodies,failures=failures,results=[dict(callId=event['data']['message']['toolCallId'],code=event['data']['error']['code'],source=event.get('sourceEventSeqs')) for event in events if event['type']=='tool/result'],tail=[event['type'] for event in events[-2:]]))
        finally:
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps([dict(test=test,events=events_for(test['action'])) for test in cases()]),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_tool_recovery.mts','V4 live/tail recovery, exact turn/step and append matching, deterministic messages and real Agent failure/aggregate cleanup.',[Path(__file__).resolve(),ROOT/'dsh/core/session/repair.py',ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/core/agent_lifecycle_current.py',ROOT/'dsh/session/cold_read.py'],prepare=prepare)
