import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.api.session_assistant_listeners import SessionAssistantStreamsListener
from dsh.api.session_history_authorized import SessionHistoryController
from dsh.api.session_listeners import ListenerBuffer
from scripts.rc022_assistant_reconnect_probe import observe


@pytest.mark.asyncio
async def test_shared_baselines_and_independent_arrival_cuts(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==10
    assert rows['opening']['stable'] and rows['opening']['value']['ordinal']==1
    assert rows['chunk-baseline']['old']['baseline']['activeAttempt']['nextIndex']==0
    assert rows['chunk-baseline']['value']['baseline']['activeAttempt']['nextIndex']==1
    assert rows['second-connection']['shared'] and rows['second-connection']['value']['ordinal']==0
    assert [value['frame']['type'] for value in rows['uncovered-frames']['values']]==['chunk','end']
    assert rows['disposed-baseline']['value']['baseline']==dict(revision=0)
    assert rows['new-lifecycle']['wire']['frame']['startedAfterSeq']==0
    assert rows['gap-clears-attempt']['value']['baseline']==dict(revision=3)
    assert rows['unbound-queue']['value']==dict(marker='still-open')
    assert rows['cancelled']['ended']==[True,True]


@pytest.mark.asyncio
async def test_actual_generating_agent_reconnect_and_cancel_then_disposal(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from scripts.rc022_inbox_readers_probe import message
    fixture=await setup(tmp_path/'journal');ctx=fixture.ctx;controller=AbortController();handle=queue=listener=None
    try:
        history=SessionHistoryController(ctx)
        handle=await ctx.agents.create(dict(sessionId='generating',agentOptions=dict(provider='script',model='model')))
        agent=handle.agent;agent.followup(message('task'))
        async def partial():
            while True:
                stream=history.streamsListener.streams.get(agent.id)
                baseline=stream.snapshot() if stream is not None else {}
                if baseline.get('activeAttempt',{}).get('nextIndex',0)>=2:return baseline
                await asyncio.sleep(0)
        baseline=await asyncio.wait_for(partial(),5)
        assert 'partial' in json.dumps(baseline)
        queue=ListenerBuffer(ctx,controller.signal);listener=history.streamsListener.bind(agent.id,controller.signal,queue)
        opening=listener.snapshot();assert opening['ordinal']==0 and opening['baseline'] is baseline
        agent.cancel();await asyncio.wait_for(agent.whenIdle(),5)
        values=queue.items();ending=await asyncio.wait_for(values.__anext__(),5)
        assert ending['type']=='assistant-stream' and ending['frame']['type']=='end'
        assert 'activeAttempt' not in listener.snapshot()['baseline']
        await handle.dispose();handle=None
        assert listener.snapshot()['baseline']==dict(revision=0)
        await values.aclose()
    finally:
        controller.abort()
        if listener is not None:listener.dispose()
        if queue is not None:queue.dispose()
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_binding_keeps_shared_queue_usable():
    ctx=Context();controller=AbortController();streams=SessionAssistantStreamsListener(ctx);queue=ListenerBuffer(ctx,controller.signal)
    original=ctx.on
    def fail(*_,**__):raise RuntimeError('assistant registration failed')
    ctx.on=fail
    try:
        with pytest.raises(RuntimeError,match='assistant registration failed'):
            streams.bind('target',controller.signal,queue)
        assert not queue.closed
        queue.createInput(lambda value:[dict(marker=value)]).append('usable')
        values=queue.items();assert await values.__anext__()==dict(marker='usable');await values.aclose()
    finally:
        ctx.on=original;controller.abort();queue.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_owner_unload_clears_shared_reconnect_state():
    ctx=Context();controller=AbortController();queue=ListenerBuffer(ctx,controller.signal)
    def install(child):child.set_service('streamFixture',SessionAssistantStreamsListener(child))
    provider=await ctx.plugin(install);streams=ctx.streamFixture
    listener=streams.bind('target',controller.signal,queue)
    agent=NS(session=NS(id='target',seq=0))
    try:
        ctx.emit('agent/assistant-stream',dict(agent=agent,frame=dict(type='start',attemptId='attempt',revision=1,turn=1,step=1)))
        assert listener.snapshot()['baseline']['revision']==1
        await provider.dispose()
        assert streams.streams=={} and listener.snapshot()['baseline']==dict(revision=0)
        assert not queue.closed
    finally:listener.dispose();controller.abort();queue.dispose();await ctx.fiber.dispose()
