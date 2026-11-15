"""Pair actual application Cordis events over authorized HTTP and WS carriers."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_duplex_mux_probe import Client
from scripts.rc022_authorized_events_probe import error_value


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.scope import scope_target
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.host.connection.peer import Peer
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.typert.api_remotes_authorized import AuthorizedApiRemotes, API_REMOTE_FORWARDED_EVENTS
    ctx = Context(); records = {}; rows = []; clients = []; guest_stream = None; server = None
    def modify(key, mutate):
        value = mutate(records.get(key))
        if value is not None: records[key] = value
        return records.get(key)
    ctx.set_service('credentials', SimpleNamespace(modify_record=modify))
    await ctx.plugin(CurrentTypertRegistry); await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayService, dict(websocketCompression='none'))
    await ctx.plugin(AuthorizedConnectionPlugin)
    remotes = await ctx.plugin(AuthorizedApiRemotes)
    await asyncio.sleep(0)
    actions = ['event:' + entry['event'] for entry in API_REMOTE_FORWARDED_EVENTS if 'resources' in entry]
    ctx.remoteAccess.registerPolicy('guest', SimpleNamespace(bindings=lambda _: [dict(resource=dict(kind='session', id='allowed'), role=dict(actions=actions))]))
    guest = Peer(ctx, dict(principal=dict(kind='guest')))
    guest_control = AbortController()
    async def http(path, body=None):
        reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
        try:
            headers = ('POST' if body is not None else 'GET') + ' ' + path + ' HTTP/1.1\r\nHost: 127.0.0.1:' + str(server.listened_port) + '\r\nConnection: close\r\n'
            data = b''
            if body is not None:
                cookie, value = body
                data = json.dumps(value).encode('utf-8')
                headers += 'Cookie: ' + cookie + '\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(data)) + '\r\n'
            writer.write(headers.encode('utf-8') + b'\r\n' + data); await writer.drain()
            raw = await asyncio.wait_for(reader.read(), 2)
            head, payload = raw.split(b'\r\n\r\n', 1); lines = head.decode('utf-8').split('\r\n')
            return dict(status=int(lines[0].split()[1]), headers={key.lower(): value.strip() for key, value in (line.split(':', 1) for line in lines[1:])}, body=payload)
        finally:
            writer.close(); await writer.wait_closed()
    async def result(cookie, client_id, event_id, outcome):
        response = await http('/api/$events/result', (cookie, dict(type='client-request', rpcId='answer', method='$events/result', payload=dict(args=dict(clientId=client_id, eventId=event_id, outcome=outcome)))))
        return dict(status=response['status'], body=json.loads(response['body']))
    async def open_socket(cookie, stream_id):
        client = await Client().connect(server.listened_port, cookie=cookie); clients.append(client)
        await client.send(dict(type='open', streamId=stream_id, endpoint='$events', payload=dict(args={})))
        return client, await client.receive()
    agent = SimpleNamespace(id='agent-fixture', ctx=ctx.extend({}))
    fallback = [0]
    async def delegate(): fallback[0] += 1; return dict(fallback=True)
    async def waterfall(event):
        try: return dict(value=await ctx.waterfall(scope_target(ctx, agent), event, dict(agent=agent, question='q'), delegate))
        except Exception as error: return dict(error=error_value(error))
    try:
        server = WebServerService(ctx, host='127.0.0.1', port=0); ctx.set_service('webServer', server)
        async def mounted():
            while server.match('/connect') is None: await asyncio.sleep(0)
        await asyncio.wait_for(mounted(), 1); await server.start()
        token = ctx.connection.browser_auth.launch_token
        cookie_a = (await http('/connect?token=' + token + '&interactions=answer'))['headers']['set-cookie'].split(';')[0]
        cookie_b = (await http('/connect?token=' + token + '&interactions=answer'))['headers']['set-cookie'].split(';')[0]
        a, ar = await open_socket(cookie_a, 'a'); b, br = await open_socket(cookie_b, 'b')
        rows.append(dict(name='ready', frames=[dict(type=frame['type'], streamId=frame['streamId'], value={key: value for key, value in frame['value'].items() if key != 'clientId'}) for frame in (ar, br)]))
        rows.append(dict(name='allowlist', entries=[dict(event=entry['event'], mode=entry['mode'], resources=list(entry.get('resources', {}))) for entry in API_REMOTE_FORWARDED_EVENTS]))
        async def empty():
            if False: yield
        guest_stream = await ctx.typertGateway.wireStream.open('$events', dict(args={}), empty(), guest, guest_control.signal)
        await guest_stream.__anext__()
        for entry in API_REMOTE_FORWARDED_EVENTS:
            if entry['mode'] != 'emit': continue
            event = entry['event']
            args = [dict(sessionId='allowed', title='Whole')] if event == 'api-session/added' else ['allowed', dict(private='whole')] if event.startswith('api-session/') else [dict(event=event)]
            ctx.emit(event, *args)
        owner_a = [await a.receive() for _ in range(29)]; owner_b = [await b.receive() for _ in range(29)]
        guest_frames = [await asyncio.wait_for(guest_stream.__anext__(), 1) for _ in range(5)]
        rows.append(dict(name='all-broadcasts', ownerA=owner_a, ownerB=owner_b, guest=guest_frames))
        pending = asyncio.create_task(waterfall('approval/request'))
        af, bf = await a.receive(), await b.receive(); event_id = af['value']['eventId']
        rows.append(dict(name='waterfall', frame={key: value for key, value in af['value'].items() if key != 'eventId'}, sameEvent=event_id == bf['value']['eventId']))
        foreign = await result(cookie_b, ar['value']['clientId'], event_id, dict(kind='result', value='foreign'))
        own = await result(cookie_a, ar['value']['clientId'], event_id, dict(kind='result', value=dict(approved=True)))
        cancelled = await b.receive()
        rows.append(dict(name='http-answer-binding', foreign=foreign, own=own, settlement=await pending, cancelled=dict(type=cancelled['value']['type'], sameEvent=cancelled['value']['eventId'] == event_id), fallback=fallback[0]))
        pending = asyncio.create_task(waterfall('user-questions/request')); af, bf = await a.receive(), await b.receive(); event_id = af['value']['eventId']
        await result(cookie_a, ar['value']['clientId'], event_id, dict(kind='next'))
        rows.append(dict(name='delegation-waits', pending=not pending.done(), fallback=fallback[0]))
        await result(cookie_b, br['value']['clientId'], event_id, dict(kind='next'))
        rows.append(dict(name='delegation-next', settlement=await pending, fallback=fallback[0]))
        pending = asyncio.create_task(waterfall('approval/request')); await a.receive(); await b.receive()
        await remotes.dispose()
        rows.append(dict(name='application-unload', settlement=await pending, frames=[await a.receive(), await b.receive()]))
        guest_control.abort(); await guest_stream.aclose(); guest_stream = None
        remotes = await ctx.plugin(AuthorizedApiRemotes)
        await a.send(dict(type='open', streamId='replacement', endpoint='$events', payload=dict(args={})))
        fresh = await a.receive()
        ctx.emit('plugin-manager/changed', dict(revision=2))
        notification = await a.receive()
        rows.append(dict(name='application-reload', ready=fresh['value']['type'], distinctGeneration=fresh['value']['clientId'] != ar['value']['clientId'], notification=notification))
        return rows
    finally:
        guest_control.abort()
        if guest_stream is not None: await guest_stream.aclose()
        await remotes.dispose()
        for client in clients: await client.close()
        await guest.dispose()
        if server is not None: await server.stop()
        await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_event_composition.mts', 'Actual application-selected Cordis event source, full declarations, resource-bearing session notifications, real WS event generations, real HTTP same-Peer answers, host waterfall continuation and plugin unload/reload.', [Path(__file__).resolve(), ROOT/'dsh/typert/api_remotes_authorized.py', ROOT/'dsh/typert/gateway_authorized.py'])
