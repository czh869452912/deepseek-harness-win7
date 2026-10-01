"""WebSocket logical stream mux using the Python 3.8-compatible wsproto codec."""
import asyncio
import json

from wsproto import WSConnection, ConnectionType
from wsproto.connection import ConnectionState
from wsproto.events import AcceptConnection, TextMessage, BytesMessage, Ping, CloseConnection

from dsh.core.abort import AbortController
from dsh.typert.artifact import UNDEFINED


def parse_message(text):
    value = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    if type(value) is not dict or not isinstance(value.get("streamId"), str) or not value["streamId"]:
        raise ValueError("invalid Remote stream client message")
    if value.get("type") == "cancel" and set(value) == {"type", "streamId"}:
        return value
    if value.get("type") == "open" and set(value) == {"type", "streamId", "endpoint", "payload"} and isinstance(value["endpoint"], str) and value["endpoint"]:
        return value
    raise ValueError("invalid Remote stream client message")


async def reject_upgrade(writer, status):
    reason = "Unauthorized" if status == 401 else "Forbidden"
    text = "HTTP/1.1 {} {}\r\nConnection: close\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\n\r\n{}".format(status, reason, len(reason), reason.lower())
    writer.write(text.encode("ascii"))
    await writer.drain()
    writer.close()


class RemoteStreamMux:
    def __init__(self, open_stream, failure, heartbeat_ms):
        self.open_stream, self.failure, self.heartbeat_ms = open_stream, failure, heartbeat_ms
        self.connections = {}
        self.closed = False

    async def upgrade(self, request, writer):
        if self.closed:
            writer.close()
            return
        connection = MuxConnection(request, writer, self.open_stream, self.failure, self.heartbeat_ms)
        task = asyncio.create_task(connection.run())
        self.connections[connection] = task
        try:
            await task
        finally:
            self.connections.pop(connection, None)

    async def close(self):
        self.closed = True
        active = list(self.connections.items())
        for connection, _ in active:
            connection.writer.close()
        await asyncio.gather(*(task for _, task in active), return_exceptions=True)


class MuxConnection:
    def __init__(self, request, writer, open_stream, failure, heartbeat_ms):
        self.request, self.writer, self.open_stream, self.failure = request, writer, open_stream, failure
        self.heartbeat_ms = heartbeat_ms
        self.codec, self.lock, self.streams = WSConnection(ConnectionType.SERVER), asyncio.Lock(), {}
        self.closed = False

    async def send_event(self, event):
        async with self.lock:
            self.writer.write(self.codec.send(event))
            await self.writer.drain()

    async def send(self, message):
        message = {key: value for key, value in message.items() if value is not UNDEFINED}
        text = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        await self.send_event(TextMessage(data=text))

    async def terminate(self, code, reason):
        try:
            if self.codec.state == ConnectionState.OPEN:
                await self.send_event(CloseConnection(code=code, reason=reason))
        except ConnectionError:
            # A reset peer cannot receive a close frame. Physical teardown still
            # completes; this is not a process-level application failure.
            pass
        finally:
            self.writer.close()

    async def pump(self, message, controller):
        source = None
        try:
            source = await self.open_stream(message["endpoint"], message["payload"], controller.signal)
            async for value in source:
                await self.send({"type": "item", "streamId": message["streamId"], "value": value})
            if not controller.signal.aborted:
                await self.send({"type": "end", "streamId": message["streamId"]})
        except Exception as error:
            if not controller.signal.aborted and self.codec.state == ConnectionState.OPEN:
                try:
                    await self.send({"type": "error", "streamId": message["streamId"], "error": self.failure(error)})
                except Exception:
                    await self.terminate(1011, "Remote stream failure could not be delivered")
        finally:
            try:
                if source is not None and hasattr(source, "aclose"):
                    await source.aclose()
            finally:
                self.streams.pop(message["streamId"], None)

    async def receive(self, text):
        message = parse_message(text)
        key = message["streamId"]
        if message["type"] == "cancel":
            if key in self.streams:
                self.streams[key][0].abort("Remote stream cancelled")
            return
        if key in self.streams:
            raise ValueError("duplicate Remote stream id")
        controller = AbortController()
        task = asyncio.create_task(self.pump(message, controller))
        self.streams[key] = (controller, task)
        # Upstream observes both pump settlements with done.then(remove, remove).
        # A pump may finish before run() gathers active iterators on socket close.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def run(self):
        heartbeat = None
        try:
            headers = [(key.encode("ascii"), value.encode("latin-1")) for key, value in self.request["headers"].items()]
            self.codec.initiate_upgrade_connection(headers, self.request.get("raw_url", self.request["path"]))
            list(self.codec.events())
            await self.send_event(AcceptConnection())
            async def beat():
                try:
                    while not self.closed:
                        await asyncio.sleep(self.heartbeat_ms / 1000)
                        await self.send_event(Ping())
                except (ConnectionError, OSError):
                    self.writer.close()
            heartbeat = asyncio.create_task(beat())
            parts, total = [], 0
            while not self.writer.is_closing():
                data = await self.request["reader"].read(65536)
                if not data:
                    break
                self.codec.receive_data(data)
                for event in self.codec.events():
                    if isinstance(event, TextMessage):
                        parts.append(event.data)
                        total += len(event.data.encode("utf-8"))
                        # ws uses 100 MiB as its default maximum payload.
                        if total > 100 * 1024 * 1024:
                            await self.terminate(1009, "message too big")
                            return
                        if event.message_finished:
                            try:
                                await self.receive("".join(parts))
                            except Exception:
                                await self.terminate(1008, "invalid Remote stream request")
                                return
                            parts, total = [], 0
                    elif isinstance(event, BytesMessage):
                        await self.terminate(1003, "text messages required")
                        return
                    elif isinstance(event, Ping):
                        await self.send_event(event.response())
                    elif isinstance(event, CloseConnection):
                        if self.codec.state == ConnectionState.REMOTE_CLOSING:
                            await self.send_event(event.response())
                        return
        except ConnectionError:
            # Windows can report EOF as WinError 64/10054 during abrupt browser
            # teardown. Retire this socket and its streams like ordinary EOF.
            pass
        finally:
            self.closed = True
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            active = list(self.streams.values())
            for controller, _ in active:
                controller.abort("Remote stream socket closed")
            await asyncio.gather(*(task for _, task in active), return_exceptions=True)
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (ConnectionError, OSError):
                pass
