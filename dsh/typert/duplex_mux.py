"""Peer-bound WebSocket streams with bounded uplinks and ordered downlinks."""
import asyncio
import zlib
from types import SimpleNamespace

from wsproto import WSConnection, ConnectionType
from wsproto.connection import ConnectionState
from wsproto.events import AcceptConnection, TextMessage, BytesMessage, Ping, Pong, CloseConnection
from wsproto.extensions import PerMessageDeflate
from wsproto.frame_protocol import Opcode

from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.typert.remote import remote_error_of
from dsh.typert.rpc_result import json_projection
from dsh.typert.stream_protocol import parse_client_message
from dsh.typert.uplink_inbox import UplinkInbox


class _ThresholdDeflate(PerMessageDeflate):
    """Negotiate ws-compatible takeover; compress large text frames at level 1."""
    def frame_outbound(self, proto, opcode, rsv, data, fin):
        if opcode in (Opcode.TEXT, Opcode.BINARY):
            self._large = len(bytes(data).decode('utf-8').encode('utf-16-le', errors='surrogatepass')) // 2 >= 1024
        if opcode in (Opcode.TEXT, Opcode.BINARY, Opcode.CONTINUATION) and not getattr(self, '_large', False):
            return rsv, data
        if opcode in (Opcode.TEXT, Opcode.BINARY) and self._compressor is None:
            bits = self.client_max_window_bits if proto.client else self.server_max_window_bits
            self._compressor = zlib.compressobj(1, zlib.DEFLATED, -int(bits))
        return super().frame_outbound(proto, opcode, rsv, data, fin)


async def reject_upgrade(writer, status):
    reason = {401: 'Unauthorized', 403: 'Forbidden', 409: 'Conflict'}[status]
    body = reason.lower()
    writer.write(('HTTP/1.1 {} {}\r\nConnection: close\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\n\r\n{}'.format(status, reason, len(body), body)).encode('ascii'))
    await writer.drain()
    writer.close()


class DuplexStreamMux:
    def __init__(self, open_stream, failure, heartbeat_ms=2000, inbox_bytes=262144, compression=True):
        self.open_stream, self.failure = open_stream, failure
        self.heartbeat_ms, self.inbox_bytes, self.compression = heartbeat_ms, inbox_bytes, compression
        self.connections, self.heartbeat, self.closed = {}, None, False

    async def upgrade(self, request, writer, peer, on_close=None):
        if self.closed:
            writer.close()
            return
        connection = DuplexConnection(self, request, writer, peer, on_close)
        task = asyncio.create_task(connection.run())
        self.connections[connection] = task
        try:
            await task
        finally:
            self.connections.pop(connection, None)

    def _start_heartbeat(self):
        if self.heartbeat is None:
            self.heartbeat = asyncio.create_task(self._beat())

    async def _beat(self):
        while True:
            await asyncio.sleep(self.heartbeat_ms / 1000)
            for connection in list(self.connections):
                if connection.closed or connection.codec.state != ConnectionState.OPEN:
                    continue
                if connection.missed >= 2:
                    # Give a Pong already queued on the event loop a turn.
                    await asyncio.sleep(0)
                    if connection.missed >= 2:
                        connection.writer.close()
                    continue
                connection.missed += 1
                try:
                    await connection.send_event(Ping())
                except (ConnectionError, OSError):
                    connection.writer.close()

    async def close(self):
        self.closed = True
        if self.heartbeat is not None:
            self.heartbeat.cancel()
            await asyncio.gather(self.heartbeat, return_exceptions=True)
            self.heartbeat = None
        active = list(self.connections.items())
        for connection, _ in active:
            connection.writer.close()
        await asyncio.gather(*(task for _, task in active), return_exceptions=True)


class DuplexConnection:
    def __init__(self, owner, request, writer, peer, on_close=None):
        self.owner, self.request, self.writer, self.peer = owner, request, writer, peer
        self.codec, self.lock, self.streams = WSConnection(ConnectionType.SERVER), asyncio.Lock(), {}
        self.closed, self.missed = False, 0
        self.deflate = None
        self.peer_closes = set()
        self.on_close = on_close

    def alive(self):
        self.missed = 0

    async def send_event(self, event, activity=False):
        async with self.lock:
            if self.closed or self.writer.is_closing():
                raise ConnectionError('api gateway: Remote stream socket is closed')
            self.writer.write(self.codec.send(event))
            transport = getattr(self.writer, 'transport', None)
            queued = transport is not None and transport.get_write_buffer_size() > 0
            await self.writer.drain()
            if activity and queued:
                self.alive()

    async def send(self, message):
        try:
            text = stringify_json(json_projection(message))
        except Exception as error:
            raise RuntimeError('api gateway: Remote stream item is not JSON serializable') from error
        await self.send_event(TextMessage(data=text), activity=True)
        # Source deflate completion counts as activity, including its async queue.
        if self.deflate is not None and self.deflate.enabled() and len(text.encode('utf-16-le', errors='surrogatepass')) // 2 >= 1024:
            self.alive()

    async def terminate(self, code, reason):
        try:
            if self.codec.state == ConnectionState.OPEN:
                await self.send_event(CloseConnection(code=code, reason=reason))
        except (ConnectionError, OSError):
            pass
        finally:
            self.writer.close()

    def stop(self, active, reason):
        active.abort.abort(reason)
        active.inbox.fail(reason)

    async def receive(self, text):
        message = parse_client_message(text)
        key, kind = message['streamId'], message['type']
        active = self.streams.get(key)
        if kind == 'open':
            if active is not None:
                raise ValueError('api gateway: duplicate Remote stream id')
            control = AbortController()
            inbox = UplinkInbox(self.owner.inbox_bytes, message['endpoint'], control.abort)
            active = SimpleNamespace(abort=control, inbox=inbox, done=None)
            self.streams[key] = active
            active.done = asyncio.create_task(self.pump(message, active))
            def remove(done):
                self.streams.pop(key, None)
                if not done.cancelled():
                    done.exception()
            active.done.add_done_callback(remove)
        elif active is not None:
            if kind == 'item':
                active.inbox.push(message.get('value', UNDEFINED), len(text.encode('utf-8')))
            elif kind == 'end':
                active.inbox.end()
            else:
                self.stop(active, RuntimeError('Remote stream cancelled'))

    async def pump(self, message, active):
        source, error = None, None
        try:
            stream_id = message['streamId']
            frame = stringify_json(dict(type='item', streamId=stream_id, value=None))
            window = dict(maxBytes=self.owner.inbox_bytes, frameOverheadBytes=len(frame.encode('utf-8')) - 4)
            source = await self.owner.open_stream(message['endpoint'], message['payload'], active.inbox, self.peer, active.abort, window)
            async for value in source:
                await self.send(dict(type='item', streamId=stream_id, value=value))
        except Exception as caught:
            error = caught
        finally:
            if source is not None and hasattr(source, 'aclose'):
                try:
                    await source.aclose()
                except Exception as caught:
                    if error is None:
                        error = caught
        active.inbox.fail(RuntimeError('Remote stream ended'))
        if active.abort.signal.aborted:
            reason = active.abort.signal.reason
            if remote_error_of(reason) is not None:
                await self.send_failure(message['streamId'], reason)
            return
        if error is not None:
            await self.send_failure(message['streamId'], error)
            return
        try:
            await self.send(dict(type='end', streamId=message['streamId']))
        except Exception as caught:
            await self.send_failure(message['streamId'], caught)

    async def send_failure(self, stream_id, error):
        if self.closed or self.codec.state != ConnectionState.OPEN or self.writer.is_closing():
            return
        try:
            await self.send(dict(type='error', streamId=stream_id, error=self.owner.failure(error)))
        except Exception:
            await self.terminate(1011, 'Remote stream failure could not be delivered')

    async def run(self):
        unbind = None
        try:
            headers = [(key.encode('ascii'), value.encode('latin-1')) for key, value in self.request['headers'].items()]
            self.codec.initiate_upgrade_connection(headers, self.request.get('raw_url', self.request['path']))
            list(self.codec.events())
            self.deflate = _ThresholdDeflate() if self.owner.compression else None
            await self.send_event(AcceptConnection(extensions=[self.deflate] if self.deflate is not None else []))
            def peer_left():
                task = start_coroutine(self.terminate(1001, 'peer left'))
                self.peer_closes.add(task)
                task.add_done_callback(self.peer_closes.discard)
            try:
                if self.peer.signal.aborted:
                    raise RuntimeError('Peer disposed')
                unbind = self.peer.ctx.effect(lambda: peer_left, 'api-gateway: Remote stream socket bound to its Peer')
            except Exception:
                await self.terminate(1001, 'peer left')
                return
            self.owner._start_heartbeat()
            parts, size = [], 0
            while not self.writer.is_closing():
                data = await self.request['reader'].read(65536)
                if not data:
                    break
                self.codec.receive_data(data)
                for event in self.codec.events():
                    if isinstance(event, TextMessage):
                        parts.append(event.data)
                        size += len(event.data.encode('utf-8'))
                        if size > 100 * 1024 * 1024:
                            await self.terminate(1009, 'message too big')
                            return
                        if event.message_finished:
                            self.alive()
                            try:
                                await self.receive(''.join(parts))
                            except Exception:
                                await self.terminate(1008, 'invalid Remote stream request')
                                return
                            parts, size = [], 0
                    elif isinstance(event, BytesMessage):
                        self.alive()
                        await self.terminate(1003, 'text messages required')
                        return
                    elif isinstance(event, Pong):
                        self.alive()
                    elif isinstance(event, Ping):
                        await self.send_event(event.response())
                    elif isinstance(event, CloseConnection):
                        if self.codec.state == ConnectionState.REMOTE_CLOSING:
                            await self.send_event(event.response())
                        return
        except (ConnectionError, OSError):
            pass
        finally:
            self.closed = True
            if self.on_close is not None:
                self.on_close()
            active = list(self.streams.values())
            for stream in active:
                self.stop(stream, RuntimeError('Remote stream socket closed'))
            await asyncio.gather(*(stream.done for stream in active), return_exceptions=True)
            if unbind is not None:
                unbind()
            if self.peer_closes:
                await asyncio.gather(*list(self.peer_closes), return_exceptions=True)
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (ConnectionError, OSError):
                pass
