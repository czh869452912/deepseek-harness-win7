"""Candidate authorized Gateway HTTP and duplex carrier composition.

Forwarded event endpoints mount separately with their authorization owner.
"""
import asyncio
from types import SimpleNamespace

from dsh.cordis.schema import Schema as z
from dsh.core.abort import AbortController
from dsh.typert.gateway_core import AuthorizedGatewayCore
from dsh.typert.dispatch import remote_request, rpc_failure
from dsh.typert.duplex_mux import DuplexStreamMux, reject_upgrade


class AuthorizedGatewayTransport(AuthorizedGatewayCore):
    Config = z.object(dict(
        websocketHeartbeatIntervalMs=z.natural().min(1).max(2147483647).default(2000),
        streamInboxBytes=z.natural().min(1).default(262144),
        websocketCompression=z.union([z.const('none'), z.const('deflate')]).default('deflate')))

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        config = config or {}
        self.wireStream = SimpleNamespace(open=self.open_wire, failure=lambda error: rpc_failure(error)['error'])
        def rpc(child):
            child.get('connection').rpc.intercept('/api', self.claims_endpoint, self.dispatch_rpc)
        ctx.inject(['connection'], rpc)
        def web(child):
            def listen():
                mux = DuplexStreamMux(self.open_mux, self.wireStream.failure,
                    config.get('websocketHeartbeatIntervalMs', 2000), config.get('streamInboxBytes', 262144),
                    config.get('websocketCompression', 'deflate') == 'deflate')
                releases = set()
                def setup():
                    async def upgrade(request, writer):
                        admission = child.get('connection').admit_connection(request)
                        if 'rejection' in admission:
                            await reject_upgrade(writer, admission['rejection'])
                            return
                        released = []
                        def release():
                            if released:
                                return
                            # API release removes its credential synchronously.
                            done = asyncio.ensure_future(admission['release']())
                            released.append(done)
                            releases.add(done)
                            def settled(future):
                                releases.discard(future)
                                if not future.cancelled() and future.exception() is not None:
                                    child.logger('api-gateway').error('Peer release failed: %s', future.exception())
                            done.add_done_callback(settled)
                        try:
                            await mux.upgrade(request, writer, admission['peer'], on_close=release)
                        finally:
                            release()
                    undo = child.get('webServer').register_upgrade('/api/remote.mux', upgrade)
                    async def close():
                        undo()
                        await mux.close()
                        await asyncio.gather(*list(releases), return_exceptions=True)
                    return close
                child.effect(setup, 'api-gateway: /api/remote.mux WebSocket')
            ready = child.get('appReady')
            if ready is None:
                listen()
            else:
                def setup_ready():
                    state = dict(closed=False)
                    cancel = ready.onReady(lambda: None if state['closed'] else listen())
                    def close():
                        state['closed'] = True
                        cancel()
                    return close
                child.effect(setup_ready, 'api-gateway: application readiness')
        ctx.inject(['connection', 'webServer'], web)

    def claims_endpoint(self, endpoint):
        return self.resolver.claims_endpoint(endpoint)

    async def dispatch_rpc(self, endpoint, payload, signal, peer):
        return await self.invoke_rpc(endpoint, payload, signal, peer)

    async def open_wire(self, endpoint, payload, uplink, peer, signal):
        request = dict(remote_request(endpoint, payload, signal), peer=peer, uplink=uplink)
        return await self.open_stream(request, AbortController())

    async def open_mux(self, endpoint, payload, uplink, peer, control, window):
        request = dict(remote_request(endpoint, payload, control.signal), peer=peer, uplink=uplink, uplinkWindow=window)
        return await self.open_stream(request, control)
