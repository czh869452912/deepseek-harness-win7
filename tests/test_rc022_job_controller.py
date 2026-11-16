import asyncio

import pytest

from dsh.core.abort import AbortController
from dsh.jobs.controller_current import CurrentJobController
from dsh.jobs.current import CurrentLocalJobRegistry
from dsh.jobs.observe_current import OutputWaiter, sleep
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote import RemoteError, remote_methods
from scripts import rc022_job_controller_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_observer_frames_filters_errors_and_subscription_release():
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==27
    assert all(row['listeners']==0 for row in rows.values())
    assert rows['empty']['frames'][-1]['type']=='status'
    assert len([frame for frame in rows['batch']['frames'] if frame['type']=='output'])==2
    assert rows['oversized']['frames'][1]['chunks'][0]['text']=='long 🐱 chunk'
    assert rows['evicted']['frames'][1]['lossy']
    assert rows['loss-only']['frames'][1]['lossy'] and rows['loss-only']['frames'][1]['chunks'][0]['text']==''
    assert rows['loss-empty']['frames'][1]['lossy'] and rows['loss-empty']['frames'][1]['chunks']==[]
    assert not rows['rows']['early']
    assert [call for call in rows['removed']['calls'] if isinstance(call,dict) and 'readAt' in call]==[]
    assert rows['aborted']['result']['error']['original']
    for name in ('kill-missing','kill-foreign'):
        assert rows[name]['result']['error']['code']=='job/not-found'
    assert rows['kill-cancel-failed']['result']['error']['original']
    assert rows['kill-running']['calls'][-1]['kill']==['job','owner','cancelled by the user']


@pytest.mark.asyncio
async def test_real_agent_registry_observation_preserves_model_delivery(tmp_path):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx
    lease=None;futures=[];stream=None
    try:
        await ctx.plugin(CurrentLocalJobRegistry)
        await ctx.plugin(TypertRegistry)
        controller_owner=await ctx.plugin(CurrentJobController,dict(observeFlushMs=1,observeMaxFrameBytes=5))
        controller=ctx.jobController;jobs=ctx.jobs;jobs.attachController('remote-test')
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        def producer(label):
            future=asyncio.get_running_loop().create_future();futures.append(future);handles=[];reasons=[]
            def run(handle):handles.append(handle);handle.append('old ');return dict(done=future,cancel=reasons.append)
            identity=jobs.start(dict(kind='test',label=label,owner='owner',run=run))
            return identity,future,handles[0],reasons
        identity,future,handle,reasons=producer('observed')
        abort=AbortController();stream=controller.follow(dict(jobId=identity,sessionId='owner'),abort.signal)
        opened=await stream.__anext__();assert opened['type']=='opened' and opened['from']==0
        handle.append('new 🐱')
        future.set_result(dict(status='completed',result=dict(summary='done')))
        await jobs.store[identity]['settled']
        frames=[frame async for frame in stream]
        assert frames[-1]['type']=='status' and frames[-1]['job']['status']=='completed'
        assert ''.join(chunk['text'] for frame in frames if frame['type']=='output' for chunk in frame['chunks'])=='old new 🐱'
        assert jobs.store[identity]['modelCursor']==0 and not jobs.store[identity]['resultDelivered']
        model=jobs.read(identity,'owner')
        assert ''.join(chunk['text'] for chunk in model['chunks'])=='old new 🐱'
        assert model['result']==dict(summary='done')
        assert 'result' not in jobs.read(identity,'owner')
        killed,done,handle,reasons=producer('human kill')
        assert controller.kill(dict(jobId=killed,sessionId='owner'))==dict(outcome='requested')
        assert reasons==['cancelled by the user']
        with pytest.raises(RemoteError) as failure:controller.kill(dict(jobId=killed,sessionId='foreign'))
        assert failure.value.code=='job/not-found'
        done.set_result(dict(status='killed'))
        await jobs.store[killed]['settled']
        assert jobs.get(killed,'owner')['detail']=='cancelled by the user'
        assert not jobs.store[killed]['resultDelivered']
        assert controller.kill(dict(jobId=killed,sessionId='owner'))==dict(outcome='already-finished')
        assert [row['mode'] for row in remote_methods(controller) if row['method'] in ('list','follow')]==['stream','stream']
        assert controller.typertRemote['namespace']=='job'
        assert not jobs.hub.unscoped
        await controller_owner.dispose();assert ctx.get('jobController') is None
    finally:
        if stream is not None:await stream.aclose()
        for future in futures:
            if not future.done():future.set_result(dict(status='killed'))
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()


@pytest.mark.parametrize('config',[dict(observeFlushMs=0),dict(observeMaxFrameBytes=-1),dict(observeFlushMs=1.5)])
def test_controller_configuration_rejects_invalid_cadence_and_budget(config):
    assert CurrentJobController.Config.validate(config)['issues']


@pytest.mark.asyncio
async def test_waiter_preserves_second_wake_and_releases_cancelled_wait():
    waiter=OutputWaiter();controller=AbortController()
    task=asyncio.ensure_future(waiter.wait(controller.signal));await asyncio.sleep(0)
    waiter.wake();waiter.wake()
    await task
    assert waiter.dirty
    await asyncio.wait_for(waiter.wait(controller.signal),1)
    assert not waiter.dirty and not controller.signal._listeners
    task=asyncio.ensure_future(waiter.wait(controller.signal));await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert waiter.resolve is None and not controller.signal._listeners
    task=asyncio.ensure_future(sleep(60000,controller.signal));await asyncio.sleep(0)
    controller.abort(RuntimeError('closed'));await task
    assert not controller.signal._listeners
