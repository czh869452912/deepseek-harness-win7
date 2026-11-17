"""Current Schedule tool boundaries and real durable management integration."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from test_rc022_schedule_service import host
from dsh.cordis import Context
from dsh.core.abort import NEVER_ABORTED
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.core.tools import CurrentToolsPlugin,ToolExecutionInput
from dsh.core.tool_executor_native import NativeToolExecutorPlugin
from dsh.schedule.tools_current import CurrentToolSchedule,target_help
from scripts import rc022_schedule_tools_probe as probe


async def mount(ctx):
    for plugin in [CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin]:await ctx.plugin(plugin)
    return await ctx.plugin(CurrentToolSchedule)


async def call(ctx,agent,name,args):
    return await ctx.tools.execute(ToolExecutionInput('call',name,args,agent=agent,signal=NEVER_ABORTED))


@pytest.mark.asyncio
async def test_durable_create_edit_list_delete_through_tool_pipeline(host):
    ctx=host.ctx;await mount(ctx);agent=host.agents['actor'];agent.ctx=ctx
    created=await call(ctx,agent,'schedule_create',dict(title='提醒',prompt='work',rrule='DTSTART:20990101T010000Z\nRRULE:FREQ=DAILY',target='this_session'))
    assert not created.is_error and created.value['kind']=='rrule'
    identity=created.value['id'];assert 'createdAt' not in created.value
    stored=await host.service.view(dict(id=identity))
    assert stored['target']==dict(kind='session',sessionId='actor') and stored['createdAt']
    assert created.content==[dict(type='text',text=json.dumps(created.value,ensure_ascii=False,separators=(',',':')))]
    changed=await call(ctx,agent,'schedule_edit',dict(id=identity,action='update',active=False,expectedUpdatedAt=created.value['updatedAt']))
    assert changed.value['status']=='paused'
    conflict=await call(ctx,agent,'schedule_edit',dict(id=identity,action='update',title='stale',expectedUpdatedAt=created.value['updatedAt']))
    assert conflict.value==dict(id=identity,code='schedule_conflict')
    page=await call(ctx,agent,'schedule_list',dict(active=False,limit=1,offset=0,sessionId='ignored'))
    assert page.value['total']==1 and page.value['items'][0]['id']==identity
    deleted=await call(ctx,agent,'schedule_edit',dict(id=identity,action='delete'))
    assert deleted.value==dict(id=identity,deleted=True)
    missing=await call(ctx,agent,'schedule_view',dict(id=identity))
    assert missing.value==dict(id=identity,code='schedule_not_found')


@pytest.mark.asyncio
async def test_late_provider_registration_and_scope_cleanup():
    ctx=Context();holder=None
    try:
        fiber=await mount(ctx);assert ctx.tools.get('schedule_create') is None
        class Provider:
            @staticmethod
            def apply(ctx):ctx.provide('schedule',SimpleNamespace(deliveryLimits=lambda:dict(newSessionIntervalSeconds=90.0)))
        holder=await ctx.plugin(Provider)
        for _ in range(8):await asyncio.sleep(0)
        assert 'every 90 seconds' in ctx.tools.get('schedule_create').parameters['properties']['target']['description']
        await holder.dispose();holder=None
        assert ctx.tools.get('schedule_create') is None
        await fiber.dispose()
    finally:
        if holder is not None:await holder.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('args',[dict(id='id'),dict(id='id',action='remove'),dict(id='id',action='update',active='false')])
async def test_invalid_model_arguments_do_not_reach_service(args):
    ctx=Context();calls=[]
    async def edit(*args):calls.append(args);raise AssertionError('invalid dispatch reached service')
    try:
        ctx.provide('schedule',SimpleNamespace(deliveryLimits=lambda:dict(newSessionIntervalSeconds=60),edit=edit));await mount(ctx)
        agent=SimpleNamespace(options={},session=SimpleNamespace(id='root',header=SimpleNamespace(delegationDepth=0)),ctx=ctx)
        result=await call(ctx,agent,'schedule_edit',args)
        assert result.is_error and calls==[]
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scoped_dispatch_and_disclosed_results(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows=await probe.observe();(tmp_path/'schedule-tools-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    observed={row['name']:row for row in rows}
    assert observed['scope']['inside'] and not observed['scope']['outside'] and observed['scope']['outsideGuidance']==''
    assert not observed['disposed']['inside']
    for name in ['schedule_create','schedule_list','schedule_view','schedule_edit']:
        assert observed[name+'-delegated']['value']['value']['code']=='subagent_session'
        assert observed[name+'-internal']['value']['value']==dict(code='internal_error',message='The schedule operation failed.')
        assert observed[name+'-no-agent']['requests']==[]
    assert observed['create-new_once']['requests'][0][1]['target']['create']==dict(agentPreset='selected-preset')


def test_numeric_delivery_limit_uses_javascript_number_text():
    assert target_help(90.0)==target_help(90)
