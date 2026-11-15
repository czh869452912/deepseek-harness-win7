import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.core.scope import create_scope,ScopedLayers
from dsh.jobs.current import CurrentLocalJobRegistry
from dsh.jobs.events import JobEventHub,JobLayer
from scripts import rc022_job_registry_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_session_agent_job_lifecycle_and_failure_contracts(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path)
    rows={row['name']:row for row in await probe.observe()}
    assert rows['foreign']['code']=='JOB_FOREIGN_SESSION'
    assert rows['limit']['code']=='JOB_LIMIT_REACHED'
    assert rows['terminal-model']['value']['result']==dict(summary='done')
    assert 'result' not in rows['result-once']['value']
    assert rows['cancel-throw']['status']=='running'
    assert rows['wait-abort']['errorName']=='AbortError'
    assert rows['wait-timeout']['status']=='running'
    assert rows['retry-killed']['job']['detail']=='signal: SIGTERM; second'
    assert rows['settle-awaited']['value']==[True]
    assert rows['settle-wins-abort']['value']['status']=='completed'
    events=rows['teardown-first-wins']['events']
    assert [event['type'] for event in events]==['settled','removed']
    assert events[0]['cause']=='teardown' and events[0]['job']['status']=='failed'
    assert rows['teardown-first-wins']['jobs']==[]


@pytest.mark.asyncio
async def test_owner_disposal_awaits_producer_and_removes_records(tmp_path):
    fixture=await setup(tmp_path,script=[]);ctx=fixture.ctx
    await ctx.plugin(CurrentLocalJobRegistry);jobs=ctx.jobs;jobs.attachController('test')
    lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='model')))
    future=asyncio.get_running_loop().create_future();reasons=[];events=[]
    jobs.events.subscribe(dict(owners='all'),events.append)
    identity=jobs.start(dict(kind='test',label='owner cleanup',owner='owner',run=lambda _:dict(done=future,cancel=reasons.append)))
    try:
        disposal=asyncio.create_task(lease.dispose())
        for _ in range(20):
            await asyncio.sleep(0)
            if reasons:break
        assert reasons==['owner disposed'] and not disposal.done()
        assert jobs.get(identity,'owner')['status']=='stopping'
        future.set_result(dict(status='killed'));await asyncio.wait_for(disposal,2)
        assert jobs.list('owner')==[]
        assert [event['type'] for event in events]==['registered','stopping','settled','output','removed']
        assert events[2]['cause']=='teardown'
        await asyncio.sleep(0)
        assert not jobs.tasks and not jobs.owner_cleanups
    finally:
        if not future.done():future.set_result(dict(status='killed'))
        await lease.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_broken_pull_source_is_contained_and_final_spill_drains():
    ctx=Context();await ctx.plugin(CurrentLocalJobRegistry,dict(pumpPollMs=10000));jobs=ctx.jobs;jobs.attachController('test')
    future=asyncio.get_running_loop().create_future();reads=[];output=['head'];spill=['C:/owned-spill']
    def broken(offset):reads.append(offset);raise RuntimeError('broken source')
    def good(offset):
        text=''.join(output);return dict(text=text[offset:],nextOffset=len(text),lossy=False,**({} if not spill else dict(spillPath=spill[0])))
    identity=jobs.start(dict(kind='test',label='pull',output=[dict(read=broken),dict(read=good,channel='stdout')],run=lambda _:dict(done=future,cancel=lambda _:future.set_result(dict(status='killed')))))
    try:
        assert jobs.get(identity)['output']['spillPaths']==['C:/owned-spill']
        output.append('tail');spill.clear();future.set_result(dict(status='completed'));await jobs.wait(identity,1000)
        assert reads==[0]
        assert 'spillPaths' not in jobs.get(identity)['output']
        assert ''.join(chunk['text'] for chunk in jobs.read(identity)['chunks'])=='headtail'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_scope_event_routing_contains_listeners_and_effect_cleanup():
    ctx=Context();mount=create_scope(ctx,object());other=create_scope(ctx,object())
    layers=ScopedLayers(lambda _:JobLayer());warnings=[];hub=JobEventHub(layers,warnings.append);seen=[]
    hub.subscribe(ctx,dict(owner='alice'),lambda event:seen.append(('owner',event['id'])))
    hub.subscribe(mount.ctx,dict(owners='scope'),lambda event:seen.append(('scope',event['id'])))
    hub.subscribe(ctx,dict(owners='all'),lambda _:(_ for _ in ()).throw(RuntimeError('listener')))
    detach=hub.subscribe(ctx,dict(owners='all'),lambda event:seen.append(('all',event['id'])))
    try:
        hub.emit(dict(type='output',id='a'),NS(id='alice',ctx=mount.ctx))
        hub.emit(dict(type='output',id='b'),NS(id='bob',ctx=other.ctx))
        detach();hub.emit(dict(type='output',id='unowned'),None)
        assert seen==[('owner','a'),('all','a'),('scope','a'),('all','b'),('owner','unowned')]
        assert len(warnings)==3
    finally:await ctx.fiber.dispose()
