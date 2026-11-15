import asyncio
from types import SimpleNamespace as NS
import pytest
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.api.session_listeners import ListenerBuffer, EventListener, ProjectionListener, event_item
from scripts.rc022_session_listeners_probe import observe


@pytest.mark.asyncio
async def test_actual_passive_notification_order_and_lifetime(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==18
    assert rows['lazy']['calls']==[]
    assert rows['heterogeneous']['values']==[dict(value='first'),dict(value='n:2')]
    assert rows['single-consumer']['code']=='gateway/internal'
    assert rows['ready-missing']['queries']==0
    assert rows['creation-cut']['value']['value']['event']['seq']==2
    assert rows['deduplicated-suffix']['value']['value']['event']['seq']==3
    assert rows['external-batch-disposal']['rest']==dict(done=True)
    assert rows['grouped-projection']['value']['value']['changes']==[dict(key='ticks',val=5),dict(key='doubleTicks',val=10)]
    assert rows['cancel-discards-queued-projection']['value']==dict(done=True)
    assert rows['unload-wakes-reader']==dict(name='unload-wakes-reader',value=dict(done=True),queries=0)


def test_buffer_effect_failure_releases_abort_registration():
    signal=AbortController().signal
    primary=RuntimeError('effect failed')
    def fail(*_):raise primary
    with pytest.raises(RuntimeError) as failure:ListenerBuffer(NS(effect=fail),signal)
    assert failure.value is primary
    assert signal._dom_listeners=={}


@pytest.mark.asyncio
async def test_event_listener_partial_registration_failure_cleans_first_listener():
    ctx=Context();controller=AbortController();original=ctx.on;calls=[];removed=[]
    def on(name,callback,**options):
        calls.append(name)
        if len(calls)==2:raise RuntimeError('second registration failed')
        release=original(name,callback,**options)
        def dispose():removed.append(name);release()
        return dispose
    ctx.on=on
    try:
        with pytest.raises(RuntimeError,match='second registration'):
            EventListener(ctx,'target',controller.signal)
        assert removed==['session/event']
        assert controller.signal._dom_listeners=={}
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_projection_subscription_failure_releases_buffer():
    ctx=Context();controller=AbortController()
    def fail(*_):raise RuntimeError('projection subscribe failed')
    ctx.set_service('sessionProjections',NS(onEventChanged=fail))
    try:
        with pytest.raises(RuntimeError,match='projection subscribe failed'):
            ProjectionListener(ctx,'target',controller.signal)
        assert controller.signal._dom_listeners=={}
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_capture_failure_during_transform_propagates_original_error():
    ctx=Context();controller=AbortController();buffer=ListenerBuffer(ctx,controller.signal)
    primary=RuntimeError('transform failed')
    def fail():raise primary
    def transform(value):
        buffer.capture(fail)
        yield value
    buffer.createInput(transform).append(1)
    try:
        with pytest.raises(RuntimeError) as failure:await buffer.items().__anext__()
        assert failure.value is primary and controller.signal._dom_listeners=={}
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_external_buffer_survives_listener_disposal_and_stops_inside_creation_batch():
    ctx=Context();controller=AbortController();buffer=ListenerBuffer(ctx,controller.signal)
    events=[dict(seq=0,type='fixture'),dict(seq=1,type='fixture')]
    session=NS(id='target',firstLiveSeq=0,seq=2,snapshotEvents=lambda start,end:events[start:end])
    listener=EventListener(ctx,'target',controller.signal,buffer)
    listener.setCursor(-1)
    try:
        ctx.emit('session/created',session)
        values=buffer.items()
        assert (await values.__anext__())['event']['seq']==0
        listener.dispose()
        assert not buffer.closed
        waiting=asyncio.ensure_future(values.__anext__())
        marker=buffer.createInput(lambda value:[dict(marker=value)])
        marker.append('still-open')
        assert await waiting==dict(marker='still-open')
        await values.aclose()
        assert controller.signal._dom_listeners=={}
    finally:buffer.dispose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_consumer_task_cancel_disposes_buffer_and_wakes_no_later_output():
    ctx=Context();controller=AbortController();buffer=ListenerBuffer(ctx,controller.signal)
    values=buffer.items();input=buffer.createInput(lambda value:[value])
    try:
        # A queued first item establishes iteration before the next read blocks.
        input.append(1);assert await values.__anext__()==1
        waiting=asyncio.ensure_future(values.__anext__());await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):await waiting
        input.append(2)
        assert buffer.closed and controller.signal._dom_listeners=={}
        with pytest.raises(StopAsyncIteration):await values.__anext__()
    finally:await ctx.fiber.dispose()


def test_event_item_rejects_creation_gap_and_ignores_already_covered_event():
    event=dict(seq=2,type='fixture')
    session=NS(firstLiveSeq=0,snapshotEvents=lambda *_:[event])
    with pytest.raises(Exception,match='skipped seq 1'):
        event_item(dict(type='created',session=session,end=3),1)
    assert event_item(dict(type='created',session=session,end=3))==dict(events=[event],next=3)
    assert event_item(dict(type='event',event=event),3)==dict(events=[],next=3)


@pytest.mark.asyncio
async def test_observe_remote_uses_actual_gateway_resource_admission_and_cancellation(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import TypertRemoteService, RemoteError
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.api.session_history_authorized import SessionHistoryReads
    from dsh.api.session_resource import register_session_resource
    from dsh.host.connection.peer import Peer
    fixture=await setup(tmp_path/'journal');ctx=fixture.ctx;stream=None;controller=AbortController()
    try:
        for plugin in (CurrentTypertRegistry,RemoteAccessService,AuthorizedGatewayCore):await ctx.plugin(plugin)
        register_session_resource(ctx)
        api=AuthorizedSessionController.__new__(AuthorizedSessionController)
        TypertRemoteService.__init__(api,ctx,'sessionController',dict(namespace='session'))
        api.history_reads=SessionHistoryReads(ctx)
        ctx.remoteAccess.registerPolicy('guest',dict(bindings=lambda *_:[dict(resource=dict(kind='session',id='shared'),role=dict(actions=['session/observeEvent','session/projections']))]))
        guest=Peer(ctx,dict(principal=dict(kind='guest',id='guest')))
        async def open_stream(identity):
            return await ctx.typertGateway.stream(dict(namespace='session',method='observeEvent',
                args=dict(request=dict(address=dict(kind='session',sessionId=identity))),peer=guest,signal=controller.signal))
        with pytest.raises(RemoteError) as failure:
            denied=await open_stream('hidden');await denied.__anext__()
        assert failure.value.code=='remote-access/denied'
        stream=await open_stream('shared')
        assert await stream.__anext__()==dict(type='ready')
        agent=(await ctx.agents.create(dict(sessionId='shared',agentOptions=dict(provider='script',model='model')))).agent
        event=agent.session.append('fixture/tick',dict(value=1),ignorable=True)
        assert (await stream.__anext__())['event']==event
        baseline=await ctx.typertGateway.invoke(dict(namespace='session',method='projections',
            args=dict(request=dict(sessionId='shared')),peer=guest,signal=fixture.signal))
        assert baseline['kind']=='sequenced' and baseline['asOfSeq']==event['seq']
        controller.abort()
        with pytest.raises(RemoteError) as failure:await stream.__anext__()
        assert failure.value.code=='gateway/cancelled'
    finally:
        controller.abort()
        if stream is not None:await stream.aclose()
        await ctx.fiber.dispose()
