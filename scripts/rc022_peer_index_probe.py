"""Pair live Peer-specific index injection and access snapshots."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.current import CurrentWebServer
    from dsh.host.connection.peer import Peer
    from dsh.typert.remote_access import RemoteAccessService
    ctx = Context(); access_owner = await ctx.plugin(RemoteAccessService)
    server = CurrentWebServer(ctx, port=0); ctx.set_service('webServer', server)
    await asyncio.sleep(0)
    state = dict(a='first', b='second')
    def bindings(principal):
        identity = state.get(principal['id'])
        return [] if identity is None else [dict(resource=dict(kind='session', id=identity), role=dict(actions=['notes/read', 'event:notice']))]
    policy = ctx.remoteAccess.registerPolicy('guest', SimpleNamespace(bindings=bindings))
    peers = [Peer(ctx, dict(principal=principal)) for principal in [dict(kind='owner'), dict(kind='guest', id='a'), dict(kind='guest', id='b')]]
    observed = []
    def inject(table, peer):
        observed.append(peer)
        table.append(dict(kind='global', name='__PEER__', value=peer.principal))
    undo = ctx.on('webserver/index-inject', inject)
    rows = []
    def capture(name, peer):
        table = server.collectIndexInjections(peer)
        html = server.renderIndex('<html><head><script>application()</script></head><body>shell</body></html>', peer)
        rows.append(dict(name=name, table=table, samePeer=observed[-1] is peer,
                         order=html.index('__PEER__') < html.index('application()') and html.index('__DSH_BOOT_READY__') < html.index('shell'), tap=html.endswith('#tap')))
        return table
    tap = server.tap_index(lambda html: html + '#tap')
    try:
        baseline = capture('owner', peers[0])
        first = capture('guest-a', peers[1]); capture('guest-b', peers[2])
        first.append(dict(kind='global', name='external-mutation', value=True))
        state['a'] = 'updated'; ctx.remoteAccess.invalidate(peers[1].principal)
        capture('live-update', peers[1])
        rows.append(dict(name='detached', baseline=baseline[0]['value'], previous=first[0]['value']))
        policy(); capture('policy-unload', peers[1])
        tap(); capture('tap-unload', peers[0])
        await access_owner.dispose(); capture('access-unload', peers[0])
        undo(); rows.append(dict(name='listener-unload', table=server.collectIndexInjections(peers[0])))
        # Observe JSON row values, including Object.freeze's native containers.
        return json.loads(json.dumps(rows))
    finally:
        for peer in peers: await peer.dispose()
        await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_peer_index.mts', 'Actual WebServer Peer-index emit, actual RemoteAccess live principal snapshots, fresh tables, structured rows before application scripts, readiness ordering, raw tap order, policy/access/listener unload.', [Path(__file__).resolve(), ROOT/'dsh/host/webserver/current.py', ROOT/'dsh/typert/remote_access.py'])
