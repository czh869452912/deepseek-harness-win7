"""Pair actual Connection credentials, Peer claims and caller-owned routes."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_connection_auth_probe import Response


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    from dsh.host.connection.authorized import AuthorizedHostConnection
    ctx=Context();ctx.set_service('webServer',SimpleNamespace(host='10.1.2.3',protocol='https:'))
    auth=CurrentBrowserAuth(ctx,bytes(range(32)),1);rows=[]
    class Connection(Plugin):
        def apply(self,child):self.connection=AuthorizedHostConnection(child,['remote.example'],auth)
    service=await ctx.plugin(Connection);connection=ctx.connection
    def request(cookie=None,host='localhost:443'):
        headers=dict(host=host)
        if cookie:headers['cookie']=cookie
        return dict(method='GET',path='/',headers=headers)
    def state(admission):
        if 'rejection'in admission:return dict(rejection=admission['rejection'])
        peer=admission['peer'];return dict(browser=peer is connection.browserPeer,kind=peer.principal['kind'],interactions=peer.interactions)
    try:
        rows.append(dict(name='fences',unknown=state(connection.admit(request())),untrusted=state(connection.admit(request(host='evil'))),bind=connection._trusted(request(host='10.1.2.3:9000')),remote=connection.allowsRemoteAuthorities))
        writer=Response();connection.authorize_index(dict(request(),raw_url='/?token='+auth.launch_token),writer)
        browser=writer.state['headers']['set-cookie'].split(';')[0];browser_req=request(browser)
        rows.append(dict(name='browser',status=writer.state['status'],admission=state(connection.admit(browser_req))))
        cookies=[];peers=[]
        for mode in ('none','answer'):
            writer=Response();connection.authorize_connect(dict(request(),raw_url='/connect?token='+auth.launch_token+'&interactions='+mode),writer)
            cookie=writer.state['headers']['set-cookie'].split(';')[0];cookies.append(cookie);admission=connection.admit(request(cookie));peers.append(admission['peer'])
            rows.append(dict(name='api-'+mode,status=writer.state['status'],admission=state(admission),same=connection.admit(request(cookie))['peer'] is admission['peer']))
        rows.append(dict(name='independent',distinct=peers[0] is not peers[1],browser=all(peer is not connection.browserPeer for peer in peers)))
        first=connection.admit_connection(request(cookies[0]));second=connection.admit_connection(request(cookies[0]))
        rows.append(dict(name='claim',first=state(first),second=state(second),http=state(connection.admit(request(cookies[0])))))
        pending=first['release']();same=first['release']() is pending;revoked=state(connection.admit(request(cookies[0])));await pending
        rows.append(dict(name='release',same=same,revoked=revoked,aborted=peers[0].signal.aborted))
        for _ in range(2):await connection.admit_connection(browser_req)['release']()
        rows.append(dict(name='browser-release',aborted=connection.browserPeer.signal.aborted,admission=state(connection.admit(browser_req))))
        class Owner(Plugin):
            inject=['connection']
            def apply(self,child):
                principal=dict(kind='guest');self.principal=principal;self.peer=child.connection.create_peer(dict(principal=principal,interactions='none'))
                child.connection.fetch.register(dict(path='/api/fixture/value',methods=['GET'],requestBody='streaming',fetch=lambda _:dict(status=202,body='exact',headers={})))
                async def handler(endpoint,payload,signal,peer):return dict(ok=True,value=dict(kind=peer.principal['kind'],same=peer is self.peer))
                child.connection.rpc.intercept('/api',lambda _:True,handler)
        owner=await ctx.plugin(Owner);guest=owner.plugin.peer;api=connection.create_shared_fetch_handler('/api')
        req=dict(path='/api/fixture/value',method='GET',headers={})
        owner_result=await api.fetch(req,connection.browserPeer);guest_result=await api.fetch(req,guest)
        rpc=await api.fetch(dict(req,method='POST',headers={'content-type':'application/json'},body=json.dumps(dict(type='client-request',rpcId='id',method='fixture/value',payload=dict(args={},peer=dict(kind='owner')))).encode()),guest)
        rows.append(dict(name='routes',owner=owner_result['status'],guest=guest_result['status'],mode=api.requestBodyMode(req),rpc=json.loads(rpc['body']),principal=guest.principal is owner.plugin.principal))
        await owner.dispose()
        rows.append(dict(name='caller-unload',peer=guest.signal.aborted,route=(await api.fetch(req,connection.browserPeer))['status'],mode=api.requestBodyMode(req)))
        await service.dispose()
        writer=Response();connection.authorize_connect(dict(request(host='evil'),raw_url='/connect'),writer)
        rows.append(dict(name='service-unload',browser=connection.browserPeer.signal.aborted,operator=peers[1].signal.aborted,admission=state(connection.admit(request(cookies[1]))),untrusted=state(connection.admit(request(host='evil'))),connect=writer.state['status']))
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_connection_peer.mts','Actual Connection service and signed browser/API auth: shared browser, independent operators, synchronous socket claims and release revocation, caller-owned Peers/routes, exact-route owner fence, trusted RPC peer and plugin unload. Actual network upgrade remains separate.',[Path(__file__).resolve(),ROOT/'dsh/host/connection/authorized.py'])
