"""SDK 2 stdio negotiation through a disposable, fully reaped sibling."""
import asyncio

from dsh.mcp.negotiation_current import SdkError
from dsh.mcp.probe_current import negotiate_era, disarm_spent_close_guard
from dsh.mcp.stdio_client import StdioMcpClient
from dsh.mcp.negotiated_protocol_current import NegotiatedProtocol

_AUTO = dict(kind='auto', modernVersions=['2026-07-28'], fallbackAvailable=True, probe={})


class _ProbeChannel:
    def __init__(self, client):
        self.client = client
        self.onmessage = self.onerror = self.onclose = None

    async def start(self):
        # StdioMcpClient has started the raw process before calling _initialize.
        pass

    async def send(self, packet):
        await self.client._write(packet)


class _DisposableProbe(StdioMcpClient):
    def __init__(self, owner):
        super().__init__(owner.command, owner.args, owner.env, owner.cwd)
        self.channel = _ProbeChannel(self)
        self.negotiation = owner.negotiation
        self.client_info = getattr(owner, 'client_info', None)
        self.on_error = lambda error: self.channel.onerror(error) if self.channel.onerror is not None else None

    async def _initialize(self):
        return await negotiate_era(self.negotiation, self.channel, transport_kind='stdio', disposable_probe=True, client_info=self.client_info)

    async def _receive(self, packet):
        if self.channel.onmessage is not None:
            self.channel.onmessage(packet)

    async def _read_stderr(self):
        while await self.proc.stderr.read(4096):
            pass

    def _disconnect(self):
        if not self._closed and self.channel.onclose is not None:
            self.channel.onclose()
        super()._disconnect()

    async def _close(self):
        try:
            await super()._close()
        finally:
            tasks = list(getattr(self.channel, '_probe_send_tasks', ()))
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            disarm_spent_close_guard(self.channel)


class CurrentStdioMcpTransport(NegotiatedProtocol, StdioMcpClient):
    def __init__(self, command, args=None, env=None, cwd='', negotiation=None):
        super().__init__(command, args, env, cwd)
        self.negotiation = negotiation if negotiation is not None else _AUTO
        self._probe = None
        self._connect_started = False
        self._caller_closed = False
        self.negotiated = None

    @staticmethod
    def _closed_probe_error():
        return SdkError('ERA_NEGOTIATION_FAILED', 'Version negotiation failed: the transport was closed during the server/discover probe')

    async def connect(self):
        if self._connect_started or self._closed or self._closing is not None:
            raise RuntimeError('MCP transport can only be started once')
        self._connect_started = True
        sibling = self._probe = _DisposableProbe(self)
        try:
            try:
                self.negotiated = await sibling.connect()
            finally:
                # Waiting here is the replacement fence: no serving process may
                # start while the disposable process can still be alive.
                await sibling.close()
            if self._caller_closed:
                raise self._closed_probe_error()
            self._probe = None
            return await super().connect()
        except BaseException:
            caller_closed_during_probe = self._caller_closed_during_probe
            await super().close()
            if caller_closed_during_probe:
                raise self._closed_probe_error()
            raise
        finally:
            self._probe = None

    @property
    def _caller_closed_during_probe(self):
        return self._caller_closed and self.proc is None

    async def close(self):
        self._caller_closed = True
        if self._probe is not None:
            await self._probe.close()
        await super().close()
