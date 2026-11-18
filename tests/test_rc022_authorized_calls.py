import asyncio
from types import SimpleNamespace as NS
import pytest
from dsh.cordis import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.core.scope import scope_of
from dsh.host.connection.peer import Peer
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.remote_access import RemoteAccessService
from dsh.typert.remote import Remote, TypertRemoteService
from dsh.typert.authorized_calls import AuthorizedCallResolver
from scripts.rc022_authorized_calls_probe import observe


@pytest.mark.asyncio
async def test_authorized_wire_calls_precede_host_identity_activation():
    rows={row['name']:row for row in await observe()}
    for name in ['lookup-denied','lookup-invalid','scope-denied','scope-invalid','unknown-field','missing-lookup']:
        assert rows[name]['counts']['lookup']==rows[name]['counts']['context']==rows[name]['counts']['method']==0
    assert rows['lookup-allowed']['counts']==dict(lookup=1,context=0,method=1,policy=1)
    assert rows['scope-allowed']['counts']['context']==1
    assert rows['reader-all-required']['error']['code']=='remote-access/denied'
    assert rows['reader-empty']['error']['details']['reason']=='resource-invalid'
    assert rows['strict-strip-before-policy']['value']['data']==dict(title='Title')
    assert rows['strict-strip-before-policy']['value']['wire']['request']['sessionId']=='b'
    assert rows['strict-input-before-policy']['counts']['policy']==0
    assert rows['item-filter']['value']['data']==['a']
    assert rows['disposed-first']['error']['code']=='gateway/peer-disposed'


@pytest.mark.asyncio
async def test_peer_owns_scope_and_racing_close_shares_completion():
    ctx=Context();principal=dict(kind='guest',id='g');peer=Peer(ctx,dict(principal=principal,interactions='none'))
    assert peer.principal is principal and peer.interactions=='none'
    assert scope_of(peer.ctx) is peer
    assert not peer.signal.aborted
    first=peer.dispose();second=peer.dispose()
    assert first is second
    await first
    assert peer.signal.aborted
    assert str(peer.signal.reason)=='Peer %s was disposed' % peer.id
    other=Peer(ctx,dict(principal=dict(kind='owner')))
    assert other.interactions=='answer'
    await ctx.fiber.dispose()
    assert other.signal.aborted


@pytest.mark.asyncio
async def test_concurrent_receivers_keep_invocations_and_root_has_none():
    ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService)
    entered=asyncio.Event();release=asyncio.Event();count=[0]
    class Fixture(TypertRemoteService):
        def __init__(self, child):super().__init__(child,'fixture')
        @Remote
        async def slow(self):
            count[0]+=1
            if count[0]==2:entered.set()
            before=self.ctx.invocation.peer.principal
            await release.wait()
            return before,self.ctx.invocation.peer.principal
    try:
        await ctx.plugin(Fixture);resolver=AuthorizedCallResolver(ctx)
        async def invoke(identity):
            peer=Peer(ctx,dict(principal=dict(kind='owner',id=identity)))
            request=dict(namespace='fixture',method='slow',args={},peer=peer)
            prepared=await resolver.resolve(request)
            method,args=resolver.bind(prepared,NS(request=request,service='fixture',peer=peer,signal=NEVER_ABORTED))
            return await method(*args)
        first=asyncio.create_task(invoke('a'));second=asyncio.create_task(invoke('b'))
        await asyncio.wait_for(entered.wait(),1);release.set()
        assert await first==(dict(kind='owner',id='a'),)*2
        assert await second==(dict(kind='owner',id='b'),)*2
        assert ctx.invocation is None
    finally:
        release.set();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_generated_authorized_export_uses_adapter_and_its_resource_reader():
    from dsh.typert.gateway_transport import AuthorizedGatewayTransport
    from dsh.host.connection.rpc_current import full_response
    import json
    ctx = Context()
    await ctx.plugin(CurrentTypertRegistry)
    await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayTransport)
    entered = []
    class Fixture(TypertRemoteService):
        def __init__(self, child):
            super().__init__(child, 'fixture')
        def list(self, identity):
            raise AssertionError('domain method must not implement the Remote export')
        @Remote(dict(name='list', resources=dict(session=lambda identity: identity)))
        def remoteList(self, identity):
            entered.append(identity)
            return [dict(name='adapter', sessionId=identity)]
    try:
        await ctx.plugin(Fixture)
        ctx.typert.resources.register('session', dict(field='sessionId'))
        ctx.typert.register(dict(package='adapter-fixture', face='host', model={}, schemas=[], invocations=[dict(
            id='fixture#list', service='fixture', namespace='fixture', method='list',
            parameters=[dict(name='identity', wire='identity', source='json', codec=dict(mode='src-json'))],
            invocation=dict(kind='direct'), result=dict(mode='src-json'))]))
        ctx.remoteAccess.registerPolicy('guest', dict(bindings=lambda _: [dict(resource=dict(kind='session', id='allowed'),
            role=dict(actions=['fixture/list']))]))
        peer = Peer(ctx, dict(principal=dict(kind='guest', id='g')))
        denied = await ctx.typertGateway.dispatch_rpc('fixture/list', dict(args=dict(identity='denied')), NEVER_ABORTED, peer)
        assert denied['ok'] is False and not entered
        result = await ctx.typertGateway.dispatch_rpc('fixture/list', dict(args=dict(identity='allowed')), NEVER_ABORTED, peer)
        assert result == dict(ok=True, value=[dict(name='adapter', sessionId='allowed')])
        assert entered == ['allowed']
        response = full_response('adapter', result)
        assert response['status'] == 200
        assert json.loads(response['body'])['result'] == result
    finally:
        await ctx.fiber.dispose()
