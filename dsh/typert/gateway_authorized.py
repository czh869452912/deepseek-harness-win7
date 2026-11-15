"""Authorized Remote gateway with creator-owned forwarded-event registration."""
import asyncio
import inspect

from dsh.core.session.json import UNDEFINED
from dsh.typert.authorized_calls import assert_peer_live
from dsh.typert.authorized_events import AuthorizedRemoteEvents
from dsh.typert.dispatch import TypertGatewayError, rpc_failure
from dsh.typert.gateway_transport import AuthorizedGatewayTransport
from dsh.typert.stores import field


def require_interactions(peer, endpoint):
    if peer.interactions != 'answer':
        raise TypertGatewayError('interactions-forbidden', endpoint,
                                 'forwarded Remote events require interactions=answer')


def release_uplink(source):
    """Initiate the unused uplink's return without blocking stream admission."""
    async def release():
        try:
            iterator = source.__aiter__()
            close = getattr(iterator, 'aclose', None)
            if close is not None:
                done = close()
                if inspect.isawaitable(done):
                    await done
        except Exception:
            pass
    task = asyncio.ensure_future(release())
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())


class AuthorizedGatewayService(AuthorizedGatewayTransport):
    def __init__(self, ctx, config=None):
        self.events = AuthorizedRemoteEvents(ctx)
        super().__init__(ctx, config)

    def claims_endpoint(self, endpoint):
        return endpoint == '$events/result' or super().claims_endpoint(endpoint)

    async def dispatch_rpc(self, endpoint, payload, signal, peer):
        if endpoint != '$events/result':
            return await super().dispatch_rpc(endpoint, payload, signal, peer)
        try:
            assert_peer_live(peer, endpoint)
            require_interactions(peer, endpoint)
            if field(peer.principal, 'kind') != 'owner':
                raise TypertGatewayError('invocation-unavailable', endpoint,
                                         'only owner Peers answer forwarded Remote events')
            self.events.result(payload, peer)
            return dict(ok=True, value=UNDEFINED)
        except Exception as error:
            return rpc_failure(error)

    async def open_wire(self, endpoint, payload, uplink, peer, signal):
        if endpoint != '$events':
            return await super().open_wire(endpoint, payload, uplink, peer, signal)
        release_uplink(uplink)
        assert_peer_live(peer, endpoint)
        require_interactions(peer, endpoint)
        return self.events.open(payload, signal, peer)

    async def open_mux(self, endpoint, payload, uplink, peer, control, window):
        if endpoint == '$events':
            return await self.open_wire(endpoint, payload, uplink, peer, control.signal)
        return await super().open_mux(endpoint, payload, uplink, peer, control, window)

    def registerRemoteEvents(self, source, host):
        return self.events.register(source, host)

    def hasLiveClient(self):
        return self.events.has_live_client()

    def getPendingRemoteEvents(self):
        return self.events.pending_info()
