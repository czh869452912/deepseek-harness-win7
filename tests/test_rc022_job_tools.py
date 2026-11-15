import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import AbortController,NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.jobs.current import CurrentLocalJobRegistry
from dsh.jobs.tool_current import CurrentToolJobs
from dsh.jobs.render_current import render_delta,completion_notice,fit,public_job,summary
from dsh.llm.message import create_user_message
from scripts import rc022_job_tools_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_jobs_pipeline_inbox_and_session_delivery(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert all(not row['value']['isError'] for row in rows.values() if 'value' in row)
    assert rows['list-progress']['value']['value'][0]['detail']=='building'
    assert rows['live-read']['value']['value']['text']=='out\n[stderr]\nerr'
    assert rows['inline-notice']['notices'][0]['content'][0]['text'].endswith('Output:\nFINAL')
    assert rows['held-read']['value']['value']['text']=='FINAL' and not rows['held-read']['notices']
    assert rows['repeat-read']['value']['value']['text']==''
    assert rows['overflow-held']['value']['value']['text']=='head\n'+'R'*700
    assert rows['logged-inline']['value']['value']['text']==''
    assert rows['steered']['value']['value']['job']['detail']=='working; user steered'
    assert rows['steered']['progress']=='working' and not rows['no-kill-notice']['notices']


async def runtime(tmp_path,config):
    fixture=await setup(tmp_path,script=[]);ctx=fixture.ctx
    await ctx.plugin(CurrentLocalJobRegistry);plugin=await ctx.plugin(CurrentToolJobs,config)
    lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='model')))
    return ctx,plugin,lease


@pytest.mark.asyncio
async def test_wait_cancellation_detaches_signals_and_leaves_future_output(tmp_path):
    ctx,plugin,lease=await runtime(tmp_path,dict(completionDelivery='quiet'));agent=lease.agent
    future=asyncio.get_running_loop().create_future();handles=[]
    def run(handle):handles.append(handle);return dict(done=future,cancel=lambda _:future.set_result(dict(status='killed')))
    identity=ctx.jobs.start(dict(kind='test',label='cancelled wait',owner=agent.id,run=run));controller=AbortController()
    try:
        task=asyncio.create_task(ctx.tools.execute(ToolExecutionInput('wait','job_output',dict(job_id=identity,wait=True,timeout_ms=10000),agent=agent,signal=controller.signal)))
        for _ in range(10):await asyncio.sleep(0)
        controller.abort();result=await task
        assert result.is_error and not controller.signal._listeners
        assert not ctx.jobs.store[identity]['waiters']
        handles[0].append('still available');future.set_result(dict(status='completed',result='result'))
        for _ in range(10):await asyncio.sleep(0)
        result=await ctx.tools.execute(ToolExecutionInput('read','job_output',dict(job_id=identity),agent=agent,signal=NEVER_ABORTED))
        assert result.value['text']=='still available\nresult'
    finally:
        if not future.done():future.set_result(dict(status='killed'))
        await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_wake_budget_resets_only_on_user_claim_and_plugin_unload_detaches_controller(tmp_path):
    ctx,plugin,lease=await runtime(tmp_path,dict(maxConsecutiveWakes=1));agent=lease.agent;delivered=[]
    agent.followup=lambda message:delivered.append(('wake',message));agent.inject=lambda message:delivered.append(('inject',message))
    # No live registry wait: settlement's awaited flag would intentionally suppress delivery.
    async def settle():
        future=asyncio.get_running_loop().create_future();ctx.jobs.start(dict(kind='test',label='wake',owner=agent.id,run=lambda _:dict(done=future,cancel=lambda _:None)));future.set_result(dict(status='completed'))
        for _ in range(8):await asyncio.sleep(0)
    try:
        await settle();await settle()
        ctx.emit('agent/inbox/claimed',dict(agent=agent,message=delivered[0][1]));await settle()
        ctx.emit('agent/inbox/claimed',dict(agent=agent,message=create_user_message(dict(content=[],source=dict(kind='user')))));await settle()
        assert [kind for kind,_ in delivered]==['wake','inject','inject','wake']
        await plugin.dispose()
        with pytest.raises(Exception) as error:ctx.jobs.start(dict(kind='test',label='no controller',run=lambda _:None))
        assert error.value.code=='JOB_CONTROLLER_UNAVAILABLE'
    finally:await lease.dispose();await ctx.fiber.dispose()


def test_rendering_hides_log_gaps_and_bounds_utf8_notices_without_partial_ids():
    assert render_delta([dict(text='hidden',channel='log',gapBefore=True)],False,[])==''
    assert render_delta([dict(text='err',channel='stderr',gapBefore=True)],False,['full'])=='[stderr]\nerr\n[some output was dropped from memory; full output: full]'
    job=dict(id='pwsh-'+'a'*16,kind='pwsh',label='\n  first\nsecond',status='completed',startedAt=0,progress='live',detail='terminal')
    assert public_job(job)['detail']=='live'
    for cap in (1,7,8,16,39,40,64,100,300):
        text=completion_notice(dict(job,outputLimitBytes=cap))
        assert len(text.encode('utf-8'))<=cap
        if 'pwsh-' in text:assert job['id'] in text
    for cap in (1,3,5,10,30):assert len(fit('你好'*10,'\n[status: completed]',cap,'\n[output truncated]').encode('utf-8'))<=cap
    assert len(summary('🙂'*100).encode('utf-16-le','surrogatepass'))==240
