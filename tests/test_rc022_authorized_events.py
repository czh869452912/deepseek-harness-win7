import asyncio
import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from dsh.host.connection.peer import Peer
from dsh.typert.authorized_events import AuthorizedRemoteEvents, PeerEventQueue
from dsh.typert.event_protocol import parse_result
from dsh.typert.gateway_authorized import AuthorizedGatewayService
from scripts.rc022_authorized_events_probe import cases, observe


@pytest.mark.asyncio
async def test_actual_gateway_event_generation_and_peer_authorization():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 55
    assert rows['guest-ready']['live'] is False
    assert rows['guest-ready']['released'] is True
    assert rows['owner-ready']['live'] is True
    broadcast = rows['broadcasts']
    assert len(broadcast['owner']) == 4
    assert broadcast['guests'] == [dict(type='emit', event='notice', args=['a', dict(private='whole')])] * 2
    assert broadcast['readerCalls'] == 3
    assert rows['foreign-result']['result']['error']['code'] == 'gateway/interactions-forbidden'
    assert rows['next-waits']['settled'] is False
    assert rows['last-next']['settled'] == [dict(kind='next')]
    assert rows['result-cancels-others']['settled'] == [dict(kind='result')]
    assert rows['rejection']['settled'] == [dict(error=dict(name='Refusal', message='no', code='E_DENIED', details=dict(reason='fixture')))]
    assert rows['generation-reconnect']['settled'] == [dict(kind='result', value=dict(answer=7))]
    assert rows['preaborted']['listeners'] == rows['cancelled']['listeners'] == 0
    assert rows['peer-revocation']['revoked'] == dict(done=True)
    assert rows['source-withdrawal']['owner'] == rows['source-withdrawal']['guest'] == dict(done=True)
    assert rows['source-withdrawal']['sourceClosed'] is True
    assert rows['source-withdrawal']['pending'] == []
    assert rows['source-withdrawal']['live'] is False


@pytest.mark.parametrize('value', cases())
def test_protocol_accepts_only_exact_lossless_outcomes(value):
    if isinstance(value, dict) and set(value) == {'clientId', 'eventId', 'outcome'} and value['clientId'] == 'client' and value['eventId'] == 'event' and value['outcome'] in (
        dict(kind='next'), dict(kind='result'), dict(kind='result', value=None),
        dict(kind='result', value=[1, {'x': True}]),
        dict(kind='rejected', error=dict(name='Error', message='')),
        dict(kind='rejected', error=dict(name='Custom', message='why', code='E', details={'a': 1})),
    ):
        assert parse_result(value) == value
    else:
        with pytest.raises(ValueError, match='api gateway: invalid Remote event'):
            parse_result(value)


@pytest.mark.parametrize('abort', [False, True])
@pytest.mark.asyncio
async def test_event_queue_abort_discards_buffer_but_end_drains(abort):
    queue, controller = PeerEventQueue(), AbortController()
    queue.push(1); queue.push(2)
    if abort: controller.abort()
    else: queue.end()
    assert [value async for value in queue.iterate(controller.signal)] == ([] if abort else [1, 2])
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_waiting_queue_abort_and_cancel_release_listener():
    queue, controller = PeerEventQueue(), AbortController()
    stream = queue.iterate(controller.signal)
    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    controller.abort()
    with pytest.raises(StopAsyncIteration): await pending
    assert not controller.signal._listeners
    queue, controller = PeerEventQueue(), AbortController()
    stream = queue.iterate(controller.signal)
    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    assert not controller.signal._listeners
    assert queue.waiter is None


@pytest.mark.asyncio
async def test_failed_source_cancels_pending_and_allows_replacement():
    ctx = Context()
    events = AuthorizedRemoteEvents(ctx)
    peer = Peer(ctx, dict(principal=dict(kind='owner')))
    gate = asyncio.Event()
    async def source(signal):
        await gate.wait()
        if False: yield
    unregister = events.register(source, dict(home='/fixture'))
    stream = events.open(dict(args={}), AbortController().signal, peer)
    await stream.__anext__()
    settled, subject = [], object()
    events.start(dict(event='ask', request=dict(agent=subject), context=dict(value=ctx, subject=subject, agentId='a'), resolve=settled.append, reject=settled.append))
    await stream.__anext__()
    consumed = events.registration['done']
    gate.set()
    # The consumer catches the unexpected EOF; its generation has been revoked.
    await asyncio.wait_for(consumed, 1)
    assert events.registration is None
    assert len(settled) == 1 and 'ended unexpectedly' in str(settled[0])
    with pytest.raises(StopAsyncIteration): await stream.__anext__()
    assert not events.pending
    await unregister()
    next_source = events.register(source, dict(home='/replacement'))
    await next_source()
    await stream.aclose(); await peer.dispose(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_context_request_projection_present_undefined_and_invalid_signal():
    ctx = Context(); events = AuthorizedRemoteEvents(ctx); subject = object()
    source = dict(context=dict(subject=subject), request=dict(agent=subject, signal=UNDEFINED, question='q'))
    assert events.project_request(source) == (dict(question='q'), None)
    source['request']['signal'] = None
    with pytest.raises(TypeError, match='signal must be an AbortSignal'): events.project_request(source)
    source['request'] = dict(agent=subject, amount=-0.0)
    with pytest.raises(TypeError, match='not lossless'): events.project_request(source)
    source['request'] = dict(agent=object())
    with pytest.raises(TypeError, match='scoped Agent directly'): events.project_request(source)
    await ctx.fiber.dispose()


@pytest.mark.parametrize('broken', [False, True])
@pytest.mark.asyncio
async def test_unused_uplink_release_does_not_block_or_replace_admission(broken):
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    ctx = Context(); await ctx.plugin(CurrentTypertRegistry); await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayService)
    peer = Peer(ctx, dict(principal=dict(kind='owner'), interactions='none'))
    started, release = asyncio.Event(), asyncio.Event()
    class Uplink:
        def __aiter__(self):
            if broken:
                started.set()
                raise RuntimeError('iterator acquisition failed')
            return self
        async def aclose(self): started.set(); await release.wait()
    try:
        with pytest.raises(Exception, match='interactions=answer'):
            await ctx.typertGateway.wireStream.open('$events', {}, Uplink(), peer, AbortController().signal)
        await asyncio.wait_for(started.wait(), 1)
        assert not release.is_set()
    finally:
        release.set(); await asyncio.sleep(0)
        await peer.dispose(); await ctx.fiber.dispose()
