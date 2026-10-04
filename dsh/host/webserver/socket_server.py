import asyncio
import socket


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
    def __init__(self, listener, callback, on_reset):
        self.listener = listener
        self.callback = callback
        self.on_reset = on_reset
        self.loop = asyncio.get_running_loop()
        self.accept_task = self.loop.create_task(self._accept())
        self.closed = False

    async def _accept(self):
        while True:
            accepted, address = await self.loop.sock_accept(self.listener)
            owned = None
            try:
                owned = OwnedSocket(accepted.family, accepted.type, accepted.proto,
                    accepted.detach(), self.on_reset)
                owned.setblocking(False)
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

    async def wait_closed(self):
        if not self.closed:
            await self.accept_task
            return
        try:
            await self.accept_task
        except asyncio.CancelledError:
            pass
