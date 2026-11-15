import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.interaction.commands_current import CurrentCommandRuntime
from dsh.interaction.command_builtin import BUILTINS
from dsh.sdk.server import HarnessSdkJsonRpcServer
from scripts.rc022_subagent_fixture import setup
from scripts.rc022_query_activity_probe import observe
from scripts.oracles.generate_agent_machine_current_cases import response


@pytest.mark.asyncio
async def test_query_activity_observer_contract():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==13 and all(row['closed'] and row['closeCount']==1 for row in rows.values())
    assert rows['queued-input']['notifications'][0]['params']==dict(sessionId='root',commandId='outer',finishReason='completed',finalResponse='answer tail')
    assert rows['goal-first-complete']['notifications'][0]['params']['finishReason']=='max-tokens'
    assert rows['goal-first-error']['notifications'][0]['params']['finishReason']=='error'
    assert rows['goal-clear']['notifications'][0]['params']['finishReason']=='aborted'
    assert rows['shutdown']['notifications']==[]


async def harness(tmp_path):
    fixture=await setup(tmp_path/'sessions',script=[response('model answer')]*5,directory=tmp_path);ctx=fixture.ctx
    await ctx.plugin(CurrentCommandRuntime);notifications=[]
    server=HarnessSdkJsonRpcServer(ctx,NS(notify=lambda method,params:notifications.append(dict(method=method,params=params))))
    await server.initialize(dict(cwd=str(tmp_path),provider='script',model='model'))
    return ctx,server,notifications


def query(server,text,session='root',extras=()):
    return server.handle_request('session/query',dict(sessionId=session,contentBlocks=[dict(type='text',text=text),*extras]))


@pytest.mark.asyncio
async def test_actual_query_acknowledgment_and_followup_wait_through_idle(tmp_path):
    from dsh.llm.message import create_user_message
    ctx,server,notifications=await harness(tmp_path)
    async def handler(invocation):
        invocation.agent.followup(create_user_message(dict(source=dict(kind='user'),content=[dict(type='text',text='admitted')])) )
        return dict(kind='success',text='accepted')
    ctx.commands.register(dict(name='design',definitionId=BUILTINS['plan'],description='controlled input',handler=handler))
    try:
        result=await query(server,'/计划 on')
        assert result['kind']=='command' and result['execution']['result']['text']=='accepted'
        await server.wait(dict(sessionId='root'));await asyncio.sleep(0)
        completed=[row['params'] for row in notifications if row['method']=='session.query.completed']
        assert completed==[dict(sessionId='root',commandId=result['execution']['commandId'],finishReason='completed',finalResponse='model answer')]
        assert not server.query_activities and not server.command_tasks
    finally:await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_query_validation_and_exact_name_shadow_preserve_prompt(tmp_path):
    ctx,server,notifications=await harness(tmp_path);calls=[]
    async def handler(invocation):calls.append(invocation);return dict(kind='success',text='done')
    ctx.commands.register(dict(name='wish',definitionId=BUILTINS['goal'],description='goal identity',handler=handler))
    ctx.commands.register(dict(name='goal',description='third party',handler=handler))
    try:
        with pytest.raises(TypeError,match='only a non-empty'):await server.handle_request('session/query',dict(sessionId='new',contentBlocks=[],extra=True))
        with pytest.raises(TypeError,match='non-empty contentBlocks'):await server.handle_request('session/query',dict(sessionId='new',contentBlocks=[]))
        assert not ctx.agents.list()
        result=await query(server,' /goal original  ')
        assert result['kind']=='prompt' and isinstance(result['messageId'],str) and not calls
        await server.wait(dict(sessionId='root'))
        messages=[event['data'] for event in server.sessions['root'].agent.session.snapshotEvents() if event['type']=='user/message']
        assert messages[0]['content']==[dict(type='text',text=' /goal original  ')]
        result=await query(server,'/目标 task')
        assert result['kind']=='command' and len(calls)==1
        with pytest.raises(TypeError,match='one text block'):await query(server,'/目标 task',extras=[dict(type='text',text='another')])
        assert len(calls)==1 and not server.query_activities
    finally:await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_goal_terminal_and_optional_provider_unload(tmp_path):
    from dsh.goal.current import CurrentGoalService
    ctx,server,notifications=await harness(tmp_path);owner=await ctx.plugin(CurrentGoalService)
    async def handler(invocation):
        ctx.goals.create(invocation.agent,dict(objective='query goal'))
        return dict(kind='success',text='goal admitted')
    ctx.commands.register(dict(name='goal',definitionId=BUILTINS['goal'],description='actual goal',handler=handler))
    try:
        result=await query(server,'/goal')
        assert result['kind']=='command' and server.query_activities
        agent=server.sessions['root'].agent;goal=ctx.goals.get(agent)
        ctx.goals.complete(agent,dict(id=goal['id'],revision=goal['revision']))
        completed=[row['params'] for row in notifications if row['method']=='session.query.completed']
        assert completed[-1]['finishReason']=='completed' and not server.query_activities
        await query(server,'/goal',session='unload')
        assert server.query_activities
        await owner.dispose()
        completed=[row['params'] for row in notifications if row['method']=='session.query.completed']
        assert completed[-1]['finishReason']=='error' and completed[-1]['finalResponse']=='The goal service was unloaded before the goal finished.'
        assert not server.query_activities
    finally:await owner.dispose();await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_shutdown_joins_command_after_python_query_waiter_cancel(tmp_path):
    ctx,server,notifications=await harness(tmp_path);entered=asyncio.Event();release=asyncio.Event()
    async def handler(_):entered.set();await release.wait();return dict(kind='success')
    ctx.commands.register(dict(name='plan',definitionId=BUILTINS['plan'],description='held',handler=handler))
    pending=asyncio.create_task(query(server,'/plan'))
    try:
        await entered.wait();pending.cancel()
        with pytest.raises(asyncio.CancelledError):await pending
        assert server.command_tasks
        shutdown=asyncio.create_task(server.shutdown());await asyncio.sleep(0);assert not shutdown.done()
        release.set();await asyncio.wait_for(shutdown,5)
        assert not server.command_tasks and not server.query_activities and not ctx.agents.list()
    finally:release.set();await server.shutdown();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_stdio_query_dispatch_completion_and_prompt_fallback(tmp_path):
    import os
    import sys
    from pathlib import Path
    from dsh.sdk.client import create_process_deepseek_harness
    root=Path(__file__).resolve().parents[1]
    runtime=dict(command=sys.executable,args=[str(root/'tests/fixtures/rc022_sdk_query_runtime.py'),str(tmp_path)],cwd=str(root),environment=lambda:dict(os.environ),description='SDK native query',initializeTimeoutMs=10000,requestTimeoutMs=10000,shutdownTimeoutMs=5000,disposeEofGraceMs=5000,disposeGraceMs=1000)
    harness=create_process_deepseek_harness(runtime,dict(cwd=str(tmp_path),provider='script',model='model'))
    notifications=harness.client.subscribe()
    try:
        await harness.start()
        result=await harness.client.request('session/query',dict(sessionId='root',contentBlocks=[dict(type='text',text='/计划 on')]))
        assert result['kind']=='command' and result['execution']['result']['text']=='admitted'
        await harness.client.request('session/wait',dict(sessionId='root'))
        completed=[item['params'] for item in notifications.queue if item['method']=='session.query.completed']
        assert completed==[dict(sessionId='root',commandId=result['execution']['commandId'],finishReason='completed',finalResponse='query answer')]
        result=await harness.client.request('session/query',dict(sessionId='root',contentBlocks=[dict(type='text',text='ordinary prompt')]))
        assert result['kind']=='prompt' and isinstance(result['messageId'],str)
        await harness.client.request('session/wait',dict(sessionId='root'))
    finally:notifications.close();await harness.close()
    assert harness.client.child.poll()==0 and not harness.client.transport.pending
    assert all(stream.closed for stream in (harness.client.child.stdin,harness.client.child.stdout,harness.client.child.stderr))
