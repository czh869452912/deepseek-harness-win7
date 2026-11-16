"""Temporary ownership of a raw MCP channel during SDK 2 era discovery."""
import asyncio
import weakref

from dsh.mcp.negotiation_current import classify_probe_outcome, SdkError, SdkHttpError
from dsh.mcp.current import RESOURCE_SCHEMAS
from dsh.mcp.schemas import parse, SchemaError

_SPENT_CLOSE_GUARDS = weakref.WeakKeyDictionary()


def disarm_spent_close_guard(transport):
    disarm = _SPENT_CLOSE_GUARDS.pop(transport, None)
    if disarm is not None:
        disarm()


class ProbeWindow:
    def __init__(self, transport):
        self.transport = transport
        self.saved = [getattr(transport, name, None) for name in ('onmessage', 'onerror', 'onclose')]
        self.pending = None
        self.counter = 0
        self.close_delivered = False

    @classmethod
    async def open(cls, transport):
        window = cls(transport)
        transport.onmessage = window.message
        transport.onerror = window.error
        transport.onclose = window.closed
        try:
            await transport.start()
        except BaseException:
            window.detach()
            raise
        return window

    def message(self, packet):
        if self.pending is None or not isinstance(packet, dict):
            return
        identity, future = self.pending
        if packet.get('jsonrpc') != '2.0' or packet.get('id') != identity:
            return
        def valid(name):
            try:
                parse(name, packet, RESOURCE_SCHEMAS)
                return True
            except SchemaError:
                return False
        if valid('ProbeResultEnvelope'):
            outcome = dict(kind='result', result=packet['result'])
        elif valid('ProbeErrorEnvelope'):
            error = packet['error']
            outcome = dict(error, kind='rpc-error')
        else:
            return
        self.pending = None
        if not future.done():
            future.set_result(outcome)

    def error(self, error):
        if self.saved[1] is not None:
            self.saved[1](error)

    def closed(self):
        if self.pending is not None:
            _, future = self.pending
            self.pending = None
            if not future.done():
                future.set_result(dict(kind='closed'))
        self.close_delivered = True
        if self.saved[2] is not None:
            self.saved[2]()

    async def exchange(self, version, client_info, capabilities, timeout_ms):
        self.counter += 1
        identity = 'server-discover-probe-' + str(self.counter)
        future = asyncio.get_running_loop().create_future()
        self.pending = (identity, future)
        request = dict(jsonrpc='2.0', id=identity, method='server/discover', params=dict(_meta={
            'io.modelcontextprotocol/protocolVersion': version,
            'io.modelcontextprotocol/clientInfo': client_info,
            'io.modelcontextprotocol/clientCapabilities': capabilities}))

        async def send():
            try:
                await self.transport.send(request)
            except Exception as error:
                if not future.done():
                    if getattr(error, 'name', None) == 'UnauthorizedError':
                        outcome = dict(kind='auth-required', error=error)
                    elif isinstance(error, SdkHttpError):
                        outcome = dict(kind='http-error', status=error.data['status'])
                        for key, target in [('text', 'body'), ('statusText', 'statusText')]:
                            if key in error.data:
                                outcome[target] = error.data[key]
                    else:
                        outcome = dict(kind='network-error', error=error)
                    future.set_result(outcome)

        task = asyncio.create_task(send())
        tasks = getattr(self.transport, '_probe_send_tasks', None)
        if tasks is None:
            tasks = self.transport._probe_send_tasks = set()
        tasks.add(task)
        def settled(completed):
            tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(settled)
        try:
            try:
                return await asyncio.wait_for(asyncio.shield(future), max(0, timeout_ms) / 1000)
            except asyncio.TimeoutError:
                return dict(kind='timeout', timeoutMs=timeout_ms)
        finally:
            if self.pending is not None and self.pending[0] == identity:
                self.pending = None
            # As in the SDK, the timeout settles the exchange, not its raw send.
            # The channel owns outstanding sends until completion or close.

    def detach(self):
        self.pending = None
        self.transport.onmessage, self.transport.onerror = self.saved[:2]
        saved = self.saved[2]
        if self.close_delivered and saved is not None:
            spent = [False]

            def wrapped():
                if not spent[0]:
                    spent[0] = True
                else:
                    saved()

            self.transport.onclose = wrapped

            transport_ref = weakref.ref(self.transport)
            def disarm():
                transport = transport_ref()
                if transport is not None and transport.onclose is wrapped:
                    transport.onclose = saved

            _SPENT_CLOSE_GUARDS[self.transport] = disarm
        else:
            self.transport.onclose = saved

    def release(self):
        self.detach()
        original = self.transport.start
        armed = [True]

        async def start():
            if armed[0]:
                armed[0] = False
                self.transport.start = original
                return
            return await original()

        self.transport.start = start


async def negotiate_era(negotiation, transport, transport_kind='http', environment='node',
                        disposable_probe=False, default_timeout_ms=60000, client_info=None, capabilities=None):
    probe = negotiation.get('probe', {})
    timeout_ms = probe.get('timeoutMs', default_timeout_ms)
    retries = max(0, probe.get('maxRetries', 0))
    versions = [negotiation['version']] if negotiation['kind'] == 'pin' else negotiation['modernVersions']
    fallback = negotiation['kind'] == 'auto' and negotiation['fallbackAvailable']
    window = await ProbeWindow.open(transport)
    requested, corrective_used = versions[0], False
    try:
        while True:
            outcome = await window.exchange(requested, client_info or {'name': 'dsh-mcp-client', 'version': '0.0.1'},
                                            capabilities if capabilities is not None else {}, timeout_ms)
            if outcome['kind'] == 'timeout' and retries > 0:
                retries -= 1
                continue
            verdict = classify_probe_outcome(outcome, dict(clientModernVersions=versions, requestedVersion=requested,
                fallbackAvailable=fallback, environment=environment, transportKind=transport_kind))
            kind = verdict['kind']
            if kind == 'modern':
                result = dict(era='modern', version=verdict['version'], discover=verdict['discover'])
                break
            if kind == 'corrective':
                if corrective_used:
                    raise verdict['error']
                requested, corrective_used = verdict['version'], True
                continue
            if kind == 'error':
                raise verdict['error']
            closed = outcome['kind'] == 'closed'
            cause = 'the connection closed during the server/discover probe'
            if negotiation['kind'] == 'pin':
                detail = cause + ' before the server offered pinned protocol version ' if closed else 'the server did not offer pinned protocol version '
                suffix = ' (no fallback in pin mode)' if closed else ' via server/discover (no fallback in pin mode)'
                raise SdkError('ERA_NEGOTIATION_FAILED', 'Version negotiation failed: ' + detail + negotiation['version'] + suffix)
            if not fallback:
                detail = cause + ' and this client supports no' if closed else 'the server gave no modern evidence and this client supports no'
                raise SdkError('ERA_NEGOTIATION_FAILED', 'Version negotiation failed: ' + detail + ' pre-2026-07-28 protocol version to fall back to')
            if closed and not disposable_probe:
                raise SdkError('ERA_NEGOTIATION_FAILED', 'Version negotiation failed: ' + cause + ' (this transport probed in place — the disposable sibling probe requires the SDK\'s base StdioClientTransport)')
            result = dict(era='legacy')
            break
    except BaseException:
        window.detach()
        raise
    window.release()
    return result
