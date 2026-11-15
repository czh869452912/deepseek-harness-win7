"""Pair real named control tools and inbox wait resource ownership."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace):
    from dsh.core.abort import AbortController
    from dsh.core.scope import scope_of
    from dsh.core.tools import ToolExecutionInput
    from dsh.llm.message import create_user_message
    from dsh.subagent.tools_control import SubagentControlTools,DEFINITIONS
    from scripts.rc022_subagent_fixture import setup
    fixture=await setup(workspace);ctx=fixture.ctx;signal=fixture.signal;rows=[dict(kind='metadata',data=DEFINITIONS)]
    handles=[]
    async def root(identity):
        handle=await ctx.agents.create(dict(sessionId=identity,agentOptions=dict(provider='script',model='model')))
        handles.append(handle);return handle.agent
    async def child(parent,identity):
        receipt=await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId=identity,name=identity,label=identity+' task',
            prompt=[dict(type='text',text='Task')],signal=signal,delivery='caller'))
        agent=ctx.agents.get(identity)
        while agent.status!='running':await asyncio.sleep(.001)
        return receipt,agent
    def normalized(result):
        value=None if result.is_error else result.value
        if isinstance(value,dict) and 'messageId' in value:value=dict(messageId='<message>')
        return dict(isError=result.is_error,content=result.content,value=value)
    async def execute(name,args,agent,root_id='root-call',caller_signal=None):
        result=await ctx.tools.execute(ToolExecutionInput('call',name,args,agent=agent,root_call_id=root_id,signal=caller_signal or signal))
        return normalized(result)
    async def identity(agent):
        assembly=await ctx.systemPrompt.assemble(dict(agent=agent,scope=scope_of(agent.ctx) if agent is not None else None))
        return next((context['text'] for context in assembly['contexts'] if context['name']=='subagent:identity'),'')
    try:
        owner=await ctx.plugin(SubagentControlTools)
        parent=await root('root');a,sender=await child(parent,'a');b,branch=await child(parent,'b');leaf,target=await child(branch,'leaf')
        for agent in (parent,sender,target,None):rows.append(dict(kind='identity',id=agent.id if agent is not None else None,text=await identity(agent)))
        for agent,name,args in ((parent,'list_agents',{}),(sender,'list_agents',{}),
                (sender,'send_message',dict(agent='b/leaf',message='cousin')),
                (target,'send_message',dict(agent='lead',message='result')),
                (sender,'interrupt_agent',dict(agent='b/leaf')),
                (parent,'interrupt_agent',dict(agent='missing')),
                (sender,'send_message',dict(agent='a',message='self')),
                (sender,'send_message',dict(agent='missing/path',message='missing')),
                (None,'list_agents',{})):
            rows.append(dict(kind='call',tool=name,result=await execute(name,args,agent)))
        await leaf['dispose']();await b['dispose']()
        rows.append(dict(kind='call',tool='list_agents',result=await execute('list_agents',{},parent)))
        await a['dispose']()
        rows.append(dict(kind='identity',id='a',text=await identity(sender)))
        for value in (9999,3600001,1.5):rows.append(dict(kind='invalid-wait',result=await execute('wait_agent',dict(timeout_ms=value),parent)))
        rows.append(dict(kind='missing-wait',result=await execute('wait_agent',{},None)))
        timers=[];loop=asyncio.get_running_loop();real_later=loop.call_later
        def schedule(seconds,callback,*args,**kwargs):
            if seconds<10:return real_later(seconds,callback,*args,**kwargs)
            timer=NS(active=True,callback=lambda:callback(*args))
            timer.cancel=lambda:setattr(timer,'active',False)
            timers.append(timer);return timer
        def inject(agent,text):agent.inject(create_user_message(dict(content=[dict(type='text',text=text)])))
        def hooks():return [hook for name in ('agent/inbox/inserted','agent/disposed') for hook in ctx.events._hooks.get(name,[])]
        async def pending(agent,root_id='wait-call',caller_signal=None):
            before={id(hook) for hook in hooks()}
            task=asyncio.create_task(execute('wait_agent',dict(timeout_ms=10000),agent,root_id,caller_signal))
            for _ in range(1000):
                await asyncio.sleep(0)
                if task.done() or any(timer.active for timer in timers):
                    task._probe_hooks={id(hook) for hook in hooks()}-before
                    return task
            raise RuntimeError('wait did not subscribe')
        async def record(name,task):
            result=await task
            rows.append(dict(kind='wait',name=name,result=result,timers=sum(timer.active for timer in timers),
                listenersReleased=not task._probe_hooks.intersection(id(hook) for hook in hooks())))
        with patch.object(loop,'call_later',schedule):
            inject(parent,'first')
            await record('pending',await pending(parent))
            task=await pending(parent)
            for timer in list(timers):
                if timer.active:timer.callback()
            await record('same-call-timeout',task)
            inject(parent,'second');await record('new-input-same-call',await pending(parent))
            await record('new-call-pending',await pending(parent,'different-call'))
            parent.inbox.clear();task=await pending(parent);inject(parent,'arrived');await record('arrival',task)
            parent.inbox.clear();outsider=await root('outsider');task=await pending(parent)
            inject(outsider,'unrelated');await asyncio.sleep(0)
            rows.append(dict(kind='unrelated',pending=not task.done()))
            inject(parent,'mine');await record('unrelated-then-own',task)
            parent.inbox.clear();controller=AbortController();task=await pending(parent,caller_signal=controller.signal)
            controller.abort(RuntimeError('caller aborted'));await record('cancel',task)
            parent.inbox.clear();task=await pending(parent);await handles[0].dispose();await record('disposed',task)
            outsider.inbox.clear();task=await pending(outsider);await owner.dispose();await record('unloaded',task)
        owner=await ctx.plugin(SubagentControlTools,dict(interrupt=False))
        rows.append(dict(kind='optional',names=sorted(tool['name'] for tool in ctx.tools.schemas() if tool['name'] in ('list_agents','send_message','wait_agent','interrupt_agent'))))
        await owner.dispose();rows.append(dict(kind='removed',text=await identity(outsider)))
    finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=lambda:observe(WORKSPACE/'native')
    probe.main('rc022_control_tools.mts','Real named control pipeline and identity context, whole-tree running/inactive discovery, sibling relay, ancestor-only interruption, exact schemas; controlled-clock inbox waits cover repeated rootCallId, new input/calls, timeout, unrelated agents, cancellation, disposal and plugin unload.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/tools_control.py',ROOT/'dsh/subagent/wait_input.py',ROOT/'dsh/subagent/control_tool_definitions.json',ROOT/'scripts/oracles/rc022_control_tool_metadata.mts'],prepare=prepare)
