import pytest
from types import SimpleNamespace
from scripts.rc022_gateway_transport_probe import observe


@pytest.mark.asyncio
async def test_actual_authorized_gateway_duplex_http_and_retirement():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==8
    assert rows['readiness']['before']=='closed'
    assert rows['upgrade-fences']==dict(name='upgrade-fences',unknown=401,untrusted=403)
    assert rows['socket-claim']==dict(name='socket-claim',duplicate=409,http=200)
    assert rows['http-binary']['response']['parts'][0]['bytes']==[97,98,99]
    assert rows['strict-good']['frames'][1]['value']==dict(echo=7,signal=True)
    assert rows['strict-bad']['frames'][-1]['error']['code']=='gateway/input-invalid'
    assert rows['revoked-before-retirement']==dict(name='revoked-before-retirement',upgrade=401,held=True)
    assert rows['unloaded']==dict(name='unloaded',upgrade='closed',rpc=404)


@pytest.mark.asyncio
async def test_late_readiness_callback_cannot_mount_after_gateway_unloads():
    from dsh.cordis import Context
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.authorized import AuthorizedHostConnection
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_transport import AuthorizedGatewayTransport
    ctx=Context();callbacks=[]
    ctx.set_service('appReady',SimpleNamespace(onReady=lambda callback:callbacks.append(callback) or (lambda:None)))
    server=WebServerService(ctx,host='127.0.0.1',port=0);ctx.set_service('webServer',server)
    AuthorizedHostConnection(ctx,[],CurrentBrowserAuth(ctx,bytes(range(32)),1))
    await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService)
    gateway=await ctx.plugin(AuthorizedGatewayTransport)
    try:
        assert len(callbacks)==1 and server._upgrade_routes=={}
        await gateway.dispose()
        callbacks[0]()
        assert server._upgrade_routes=={}
    finally:await ctx.fiber.dispose()
