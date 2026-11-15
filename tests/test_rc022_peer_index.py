import pytest

from dsh.cordis import Context
from dsh.cordis.loader import Loader
from dsh.host.webserver.current import CurrentWebServer
from dsh.host.connection.peer import Peer
from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin, SCRIPT
from dsh.host.client_modules.registry import ClientModulesPlugin
from dsh.client.ui_theme import ClientUiThemePlugin
from scripts.rc022_peer_index_probe import observe


@pytest.mark.asyncio
async def test_peer_index_uses_fresh_live_access_and_caller_identity():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 9
    assert rows['owner']['table'][0]['value'] == dict(type='baseline', owner=True)
    for name, identity in [('guest-a', 'first'), ('guest-b', 'second'), ('live-update', 'updated')]:
        assert rows[name]['table'][0]['value'] == dict(type='baseline', owner=False, grants=[dict(resource=dict(kind='session', id=identity), actions=['notes/read'])])
        assert rows[name]['samePeer'] and rows[name]['order']
    assert rows['detached']['previous']['grants'][0]['resource']['id'] == 'first'
    assert rows['policy-unload']['table'][0]['value']['grants'] == []
    assert not rows['tap-unload']['tap']
    assert [item['name'] for item in rows['access-unload']['table']] == ['__PEER__']
    assert not rows['listener-unload']['table']


@pytest.mark.asyncio
async def test_index_consumers_accept_peer_with_real_client_module_registry(tmp_path):
    ctx = Context(); Loader(ctx, dict(baseUrl=str(tmp_path)))
    server = CurrentWebServer(ctx, port=0)
    ctx.set_service('webServer', server)
    peer = Peer(ctx, dict(principal=dict(kind='owner')))
    await ctx.plugin(ClientModulesPlugin)
    await ctx.plugin(ClientUiThemePlugin)
    compatibility = await ctx.plugin(BrowserCompatibilityPlugin)
    try:
        html = server.renderIndex('<head><script type="module" src="/app.js"></script></head><body></body>', peer)
        assert html.index(SCRIPT) < html.index('__DSH_BOOT__') < html.index('/app.js')
        assert '__DSH_BOOT_READY__' in html
        assert server.collectIndexInjections(peer)
        await compatibility.dispose()
        assert SCRIPT not in server.renderIndex('<head></head><body></body>', peer)
    finally:
        await peer.dispose(); await ctx.fiber.dispose()
