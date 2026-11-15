import pytest
import asyncio
import json
from scripts.rc022_connection_peer_probe import observe


@pytest.mark.asyncio
async def test_operator_claims_revocation_and_route_ownership():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==11
    assert rows['claim']['second']==dict(rejection=409)
    assert rows['release']==dict(name='release',same=True,revoked=dict(rejection=401),aborted=True)
    assert rows['routes']['owner']==202 and rows['routes']['guest']==403
    assert rows['routes']['rpc']['result']['value']==dict(kind='guest',same=True)
    assert rows['caller-unload']==dict(name='caller-unload',peer=True,route=404,mode='buffered')
    assert rows['service-unload']==dict(name='service-unload',browser=True,operator=True,admission=dict(rejection=401),untrusted=dict(rejection=403),connect=401)


@pytest.mark.asyncio
async def test_actual_http_channel_admits_before_body_and_carries_binary_for_operator():
    from dsh.cordis import Context
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.authorized import AuthorizedHostConnection
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    from dsh.typert.rpc_result import encode_rpc_result
    from scripts.rc022_connection_auth_probe import Response
    from scripts.rc022_rpc_http_probe import decode_response
    ctx=Context();server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    auth=CurrentBrowserAuth(ctx,bytes(range(32)),1);connection=AuthorizedHostConnection(ctx,[],auth);calls=[]
    async def handler(endpoint,payload,signal,peer):
        calls.append((endpoint,peer))
        return encode_rpc_result(dict(data=b'\x00\x80\xff'),dict(mode='src-json'))
    unregister=connection.rpc.handle('/binary',handler)
    await server.start()
    async def exchange(cookie=None,body=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',server.listened_port)
        try:
            headers=b'POST /binary/read HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n'
            if cookie:headers+=('Cookie: '+cookie+'\r\n').encode()
            payload=body if body is not None else b''
            headers+=('Content-Length: '+str(len(payload) if body is not None else 999999)+'\r\n\r\n').encode()
            writer.write(headers+payload);await writer.drain()
            return await asyncio.wait_for(reader.read(),2)
        finally:writer.close();await writer.wait_closed()
    try:
        assert b' 401 ' in await exchange()
        assert calls==[]
        writer=Response();connection.authorize_connect(dict(method='GET',headers=dict(host='127.0.0.1'),raw_url='/connect?token='+auth.launch_token),writer)
        cookie=writer.state['headers']['set-cookie'].split(';')[0]
        operator=connection.admit(dict(headers=dict(host='127.0.0.1',cookie=cookie)))['peer']
        payload=json.dumps(dict(type='client-request',rpcId='id',method='read',payload={})).encode()
        raw=await exchange(cookie,payload);head,body=raw.split(b'\r\n\r\n',1)
        headers={key.lower():value.strip() for key,value in (line.split(':',1) for line in head.decode().split('\r\n')[1:])}
        result=decode_response(dict(status=200,headers=headers,body=body))
        assert result['parts'][0]['bytes']==[0,128,255]
        assert calls==[('read',operator)]
        admission=connection.admit_connection(dict(headers=dict(host='127.0.0.1',cookie=cookie)))
        await admission['release']()
        assert b' 401 ' in await exchange(cookie)
        unregister()
        assert server.match('/binary/read') is None
    finally:
        await server.stop();await ctx.fiber.dispose()
