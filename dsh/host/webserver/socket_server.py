import asyncio
import socket
from asyncio.sslproto import SSLProtocol


class OwnedTLSProtocol(SSLProtocol):
    """Python 3.8 adapter: observe raw closure even before the TLS handshake."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = self._loop.create_future()

    def connection_lost(self, error):
        try:
            super().connection_lost(error)
        finally:
            if not self.closed.done():
                self.closed.set_result(None)


class OwnedSocket(socket.socket):
    def __init__(self, family, socket_type, protocol, descriptor, on_reset):
        super().__init__(family, socket_type, protocol, fileno=descriptor)
        self.on_reset = on_reset

    def shutdown(self, how):
        try:
            super().shutdown(how)
        except ConnectionResetError as error:
            if getattr(error, 'winerror', None) != 10054:
                raise
            self.on_reset(error)


class OwnedSocketServer(asyncio.AbstractServer):
    def __init__(self, listener, callback, on_reset, ssl_context=None):
        self.listener = listener
        self.callback = callback
        self.on_reset = on_reset
        self.loop = asyncio.get_running_loop()
        self.accept_task = self.loop.create_task(self._accept())
        self.closed = False
        self.ssl_context = ssl_context
        self.handshakes = {}

    async def _handshake(self, record):
        record['started'] = True
        owned = record['socket']
        transport = None
        tls_protocol = None
        ready = self.loop.create_future()
        succeeded = False
        try:
            reader = asyncio.StreamReader(loop=self.loop)
            protocol = asyncio.StreamReaderProtocol(reader, self.callback, loop=self.loop)
            tls_protocol = OwnedTLSProtocol(self.loop, protocol, self.ssl_context, ready,
                server_side=True, ssl_handshake_timeout=60)
            transport, _ = await self.loop.connect_accepted_socket(lambda: tls_protocol, owned)
            await ready
            succeeded = True
        except (OSError, ConnectionError):
            # Invalid/untrusted or plaintext clients do not stop the listener.
            pass
        finally:
            if not succeeded:
                if transport is not None:
                    transport.abort()
                    await asyncio.shield(tls_protocol.closed)
                elif tls_protocol is not None and tls_protocol._transport is not None:
                    tls_protocol._transport.abort()
                    await asyncio.shield(tls_protocol.closed)
                elif owned.fileno() != -1:
                    owned.close()
            self.handshakes.pop(asyncio.current_task(), None)

    async def _accept(self):
        while True:
            accepted, address = await self.loop.sock_accept(self.listener)
            owned = None
            try:
                owned = OwnedSocket(accepted.family, accepted.type, accepted.proto,
                    accepted.detach(), self.on_reset)
                owned.setblocking(False)
                if self.ssl_context is not None:
                    record = dict(socket=owned, started=False)
                    task = self.loop.create_task(self._handshake(record))
                    self.handshakes[task] = record
                    owned = None
                    continue
                reader = asyncio.StreamReader(loop=self.loop)
                protocol = asyncio.StreamReaderProtocol(reader, self.callback, loop=self.loop)
                await self.loop.connect_accepted_socket(lambda: protocol, owned)
                owned = None
            finally:
                accepted.close()
                if owned is not None:
                    owned.close()

    @property
    def sockets(self):
        return () if self.closed else (self.listener,)

    def get_loop(self):
        return self.loop

    def is_serving(self):
        return not self.closed and not self.accept_task.done()

    async def start_serving(self):
        if self.closed:
            raise RuntimeError('webserver: listener is closed')

    async def serve_forever(self):
        await self.accept_task

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.accept_task.cancel()
        self.listener.close()
        for task, record in list(self.handshakes.items()):
            task.cancel()
            if not record['started']:
                record['socket'].close()

    async def wait_closed(self):
        if not self.closed:
            await self.accept_task
            return
        try:
            await self.accept_task
        except asyncio.CancelledError:
            pass
        await asyncio.gather(*list(self.handshakes), return_exceptions=True)
        self.handshakes.clear()
