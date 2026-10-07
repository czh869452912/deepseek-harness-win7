import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from wsproto import WSConnection, ConnectionType
from wsproto.events import Request, AcceptConnection, TextMessage, Ping, CloseConnection
from dsh.cordis.context import Context
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote import Remote, TypertRemoteService
from dsh.typert.gateway import TypertGatewayService
from dsh.host.connection.rpc_host import HostConnectionService
from dsh.host.connection.http_bridge import bridge_handler
from dsh.host.webserver.webserver import WebServerService
from dsh.fs.tool_read_render import build_window, format_read_output
from dsh.cordis.json_text import stringify_json

spec = importlib.util.spec_from_file_location('unicode_http_fixture', Path(__file__).with_name('deepseek_http_python.py'))
http_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http_fixture)


class Streams(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, 'fixture')

    @Remote
    def echo(self, value):
        return value

    @Remote({'mode': 'stream'})
    async def echo_stream(self, value):
        yield value


class Client:
    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection('127.0.0.1', port)
        self.codec, self.events = WSConnection(ConnectionType.CLIENT), []
        self.writer.write(self.codec.send(Request(host='127.0.0.1:'+str(port), target='/api/remote.mux')))
        await self.writer.drain()
        assert isinstance(await self.next_event(), AcceptConnection)
        return self

    async def next_event(self):
        while not self.events:
            data = await asyncio.wait_for(self.reader.read(65536), 5)
            if not data:
                raise EOFError('socket closed')
            self.codec.receive_data(data)
            self.events.extend(self.codec.events())
        return self.events.pop(0)

    async def receive(self):
        parts = []
        while True:
            event = await self.next_event()
            if isinstance(event, Ping):
                self.writer.write(self.codec.send(event.response()))
                await self.writer.drain()
            elif isinstance(event, TextMessage):
                parts.append(event.data)
                if event.message_finished:
                    text = ''.join(parts)
                    return dict(text=text, value=json.loads(text))
            elif isinstance(event, CloseConnection):
                raise ConnectionError('Unexpected mux close '+str(event.code))


async def observe():
    outcome = await build_window(['\U0001f600rest'], dict(offset=1, limit=1, maxLineLength=1, maxBytes=51200), 'fixture.txt')
    values = [('high', '\ud83d'), ('low', '\ude00'), ('keys', {'\ud83d': '\ude00'}), ('pair', '\ud83d\ude00'),
        ('astral', '\U0001f600中文'), ('ascii', 'normal'), ('read', dict(outcome=outcome, rendered=format_read_output('fixture.txt', dict(offset=1, **outcome))))]
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(Streams)
    server = WebServerService(ctx, host='127.0.0.1', port=0)
    ctx.set_service('webServer', server)
    connection = HostConnectionService(ctx, [], SimpleNamespace(is_authenticated=lambda _: True))
    server.register('prefix', '/api', bridge_handler(connection, connection.createSharedFetchHandler('/api').fetch))
    gateway = await ctx.plugin(TypertGatewayService)
    await server.start()
    client = await Client().connect(server.listened_port)
    rows = []
    try:
        for name, value in values:
            message = dict(type='open', streamId=name, endpoint='fixture/echo_stream', payload=dict(args=dict(value=value)))
            client.writer.write(client.codec.send(TextMessage(data=stringify_json(message))))
            await client.writer.drain()
            frames = [await client.receive()]
            if frames[0]['value']['type'] == 'item':
                frames.append(await client.receive())
            rows.append(dict(name=name+'/mux', value=frames))
            reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port)
            try:
                body = stringify_json(dict(type='client-request', rpcId=name, method='fixture/echo', payload=dict(args=dict(value=value)))).encode('utf-8')
                writer.write(b'POST /api/fixture/echo HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode('ascii')+b'\r\n\r\n'+body)
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(), 5)
                headers, text = raw.decode('utf-8').split('\r\n\r\n', 1)
                result = dict(status=int(headers.split(' ', 2)[1]), text=text)
                if text:
                    result['value'] = json.loads(text)
                rows.append(dict(name=name+'/rpc', value=result))
            finally:
                writer.close()
                await writer.wait_closed()
            observed = await http_fixture.observe(dict(messages=[dict(role='user', content=[dict(type='text', text=value if isinstance(value, str) else stringify_json(value))])]))
            rows.append(dict(name=name+'/llm', value=observed))
    finally:
        client.writer.close()
        await client.writer.wait_closed()
        await gateway.dispose()
        await server.stop()
        await ctx.fiber.dispose()
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            modules[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(root=str(ROOT), python=sys.version, executable=str(Path(sys.executable).resolve()), imports=modules, rows=rows,
        fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


with Path(sys.argv[2]).open('x', encoding='utf-8') as stream:
    json.dump(asyncio.run(observe()), stream, ensure_ascii=True, indent=2)
    stream.write('\n')
