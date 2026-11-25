"""Actual Python socket bridge observations for current upload carriers."""
import asyncio
from types import SimpleNamespace

from dsh.cordis.context import Context
from dsh.host.connection.current import CurrentHostConnection
from dsh.host.connection.http_current import current_bridge_handler
from dsh.host.webserver.webserver import WebServerService


async def execute(action):
    ctx = Context()
    server = WebServerService(ctx, host='127.0.0.1', port=0)
    connection = CurrentHostConnection(ctx, [], SimpleNamespace(is_authenticated=lambda _: True))
    observed = dict(received='', called=False)
    async def fetch(request):
        observed['called'] = True
        observed['mode'] = 'streaming' if hasattr(request['body'], '__aiter__') else 'buffered'
        if action.get('early'):
            return dict(status=202, body='early')
        if observed['mode'] == 'streaming':
            async for chunk in request['body']:
                observed['received'] += chunk.decode('utf-8')
                if action.get('takeFirst'):
                    break
        else:
            observed['received'] = request['body'].decode('utf-8')
        observed['aborted'] = request['signal'].aborted
        return dict(status=200, body=observed['received'])
    connection.fetch.register(dict(path='/api/upload', methods=['POST'], requestBody=action['mode'], fetch=fetch))
    server.register('prefix', '/api', current_bridge_handler(connection, connection.createSharedFetchHandler('/api'), action.get('limit', 8)))
    await server.start()
    reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
    try:
        # The probe reads until EOF. Opt out of persistent connections for this request.
        headers = 'POST /api/upload HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n'
        if action.get('chunked'):
            headers += 'Transfer-Encoding: chunked\r\n'
            body = b''.join(('{:x}\r\n'.format(len(chunk.encode('utf-8'))).encode('ascii') + chunk.encode('utf-8') + b'\r\n') for chunk in action.get('chunks', []))
            if not action.get('unfinished'):
                body += b'0\r\n\r\n'
        else:
            body = ''.join(action.get('chunks', [])).encode('utf-8')
            headers += 'Content-Length: {}\r\n'.format(action.get('declared', len(body)))
        writer.write(headers.encode('ascii') + b'\r\n' + body)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), 3)
        head, content = raw.split(b'\r\n\r\n', 1)
        return dict(status=int(head.split(b' ', 2)[1]), body=content.decode('utf-8'), observed=observed)
    finally:
        writer.close()
        await writer.wait_closed()
        await server.stop()
        await ctx.fiber.dispose()
