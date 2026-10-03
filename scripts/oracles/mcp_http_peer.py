import asyncio
import json
from pathlib import Path
import sys


mode, output_path = sys.argv[1:3]
observations, tasks, writers = [], set(), set()


def record(method, headers, packet=None):
    observations.append({'method': method, 'headers': {name: headers[name] for name in
        ('accept', 'content-type', 'authorization', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id') if name in headers},
        **({'packet': packet} if packet is not None else {})})
    if method == 'GET':
        Path(output_path + '.get').touch()
    if packet is not None and packet.get('method') == 'tools/call':
        Path(output_path + '.call').touch()
    if packet is not None and packet.get('method') == 'notifications/cancelled':
        Path(output_path + '.cancel').touch()


async def respond(writer, status, content_type=None, body=b'', headers=None):
    reasons = {200: 'OK', 202: 'Accepted', 204: 'No Content', 401: 'Unauthorized', 404: 'Not Found', 405: 'Method Not Allowed'}
    lines = ['HTTP/1.1 %s %s' % (status, reasons[status]), 'Content-Length: ' + str(len(body))]
    if content_type is not None:
        lines.append('Content-Type: ' + content_type)
    lines.extend(name + ': ' + value for name, value in (headers or {}).items())
    writer.write(('\r\n'.join(lines) + '\r\n\r\n').encode('ascii') + body)
    await writer.drain()


async def handle(reader, writer):
    writers.add(writer)
    try:
        header = (await reader.readuntil(b'\r\n\r\n')).decode('latin-1').split('\r\n')
        method = header[0].split(' ')[0]
        headers = dict((name.lower(), value.strip()) for name, value in
            (line.split(':', 1) for line in header[1:] if line))
        packet = json.loads(await reader.readexactly(int(headers.get('content-length', '0')))) if method == 'POST' else None
        record(method, headers, packet)
        if method == 'GET':
            if mode == 'get-sse':
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n')
                body = b'data: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n\n'
                writer.write(('%x\r\n' % len(body)).encode('ascii') + body + b'\r\n')
                await writer.drain()
                await reader.read()
            else:
                await respond(writer, 405)
            return
        if method == 'DELETE':
            await respond(writer, 405 if mode == 'delete-405' else 204)
            return
        if 'id' not in packet:
            await respond(writer, 202)
            return
        reply = {'jsonrpc': '2.0', 'id': packet['id']}
        if packet['method'] == 'initialize':
            reply['result'] = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'controlled-http', 'version': '1'}}
        elif packet['method'] == 'tools/list':
            reply['result'] = {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
        else:
            if mode in ('cancel', 'timeout', 'close-pending'):
                await reader.read()
                return
            if mode == 'status-401':
                await respond(writer, 401, 'text/plain', b'controlled rejection')
                return
            reply['result'] = {'content': [{'type': 'text', 'text': packet['params']['arguments']['text']}]}
            if mode == 'peer-error':
                reply.pop('result')
                reply['error'] = {'code': -32602, 'message': 'controlled rejection', 'data': None}
        content_type = 'application/json'
        value = [reply] if mode == 'json-batch' else reply
        if mode == 'invalid-envelope' and packet['method'] == 'tools/call':
            value['extra'] = True
        if mode == 'unexpected-content' and packet['method'] == 'tools/call':
            content_type = 'text/plain'
        if mode == 'missing-content' and packet['method'] == 'tools/call':
            content_type = None
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if mode in ('post-sse', 'sse-bom'):
            content_type = 'text/event-stream'
            body = b': heartbeat\r\n' + b''.join(b'data: ' + line + b'\r\n' for line in
                json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8').splitlines()) + b'\r\n'
        if mode in ('json-bom', 'sse-bom'):
            body = b'\xef\xbb\xbf' + body
        await respond(writer, 200, content_type, body, {'Mcp-Session-Id': 'controlled-session'}
            if mode in ('session', 'delete-405') else {})
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writers.discard(writer)
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def main():
    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    server = await asyncio.start_server(connected, '127.0.0.1', 0)
    print('http://127.0.0.1:%s/mcp' % server.sockets[0].getsockname()[1], flush=True)
    await asyncio.get_running_loop().run_in_executor(None, sys.stdin.buffer.read)
    server.close()
    await server.wait_closed()
    for writer in list(writers):
        writer.close()
    await asyncio.gather(*list(tasks), return_exceptions=True)
    Path(output_path).write_text(json.dumps(observations, ensure_ascii=False), encoding='utf-8')


if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
