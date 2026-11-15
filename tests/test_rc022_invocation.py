import asyncio
import pytest
from dsh.cordis import Context
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.gateway_core import AuthorizedGatewayCore
from dsh.typert.remote_access import RemoteAccessService
from dsh.typert.invocation import UplinkDecoder
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from dsh.host.connection.peer import Peer
from scripts.rc022_invocation_probe import observe, Input
from scripts.rc022_authorized_calls_probe import observe as authorized


@pytest.mark.asyncio
async def test_actual_gateway_uplink_cancellation_and_close_contracts():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==13 and all(row['listeners']==0 for row in rows.values())
    assert rows['duplex']['result']['output']==[dict(echo='a',signal=True),dict(echo=dict(n=1),signal=True)]
    assert rows['strict-bad']['result']['error']==dict(code='gateway/input-invalid',details=dict(endpoint='fixture/duplex',field='uplink'))
    for name in ['peer-cancel','carrier-cancel']:
        assert rows[name]['result']['error']['code']=='gateway/cancelled'
        assert rows[name]['returned'] and rows[name]['closed']==1
    assert rows['once']['result']['value']['sameSignal'] is False
    assert rows['unread']['returned']
    assert rows['wrong-unary']['returned'] is False
    assert rows['undefined-uplink']['result']['output']==[dict(echo='undefined',signal=True)]
    assert rows['empty-uplink']['result']['output']==[]


@pytest.mark.asyncio
async def test_authorization_is_integrated_into_actual_gateway_core():
    expected=await authorized()
    actual=await authorized(use_gateway=True)
    assert actual==expected


@pytest.mark.asyncio
async def test_downlink_close_wakes_and_settles_pending_native_uplink_reads():
    source=Input([],True);controller=AbortController()
    decoder=UplinkDecoder(source,dict(mode='src-json'),'fixture/read',controller.signal,controller.abort)
    pending=asyncio.create_task(decoder.__anext__())
    for _ in range(3):await asyncio.sleep(0)
    assert decoder.reads and not pending.done()
    await decoder.aclose()
    with pytest.raises(StopAsyncIteration):await pending
    assert source.returned and not source.waiters and not decoder.reads
    assert len(controller.signal._listeners)==0


@pytest.mark.asyncio
async def test_stream_abort_preserves_remote_failure_and_never_read_stream_drops_joins():
    ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
    class Fixture(TypertRemoteService):
        def __init__(self, child):super().__init__(child,'fixture')
        @Remote(dict(mode='stream'))
        async def read(self, signal):
            async for value in self.ctx.invocation.uplink():yield value
        @Remote
        def identity(self, signal):return signal
    try:
        await ctx.plugin(Fixture);peer=Peer(ctx,dict(principal=dict(kind='owner')));carrier=AbortController()
        request=dict(namespace='fixture',method='read',args={},peer=peer,signal=carrier.signal,uplink=Input([],True))
        stream=await ctx.typertGateway.stream(request)
        assert len(peer.signal._listeners)==1
        await stream.aclose()
        assert len(peer.signal._listeners)==len(carrier.signal._listeners)==0
        stream=await ctx.typertGateway.stream(request)
        pending=asyncio.create_task(stream.__anext__())
        for _ in range(4):await asyncio.sleep(0)
        failure=RemoteError('gateway/uplink-overflow','overflow',dict(endpoint='fixture/read'))
        carrier.abort(failure)
        with pytest.raises(RemoteError) as caught:await pending
        assert caught.value is failure
        await stream.aclose()
        assert len(peer.signal._listeners)==0
        identity=dict(namespace='fixture',method='identity',args={},peer=peer,signal=NEVER_ABORTED)
        assert await ctx.typertGateway.invoke(identity) is NEVER_ABORTED
    finally:await ctx.fiber.dispose()
