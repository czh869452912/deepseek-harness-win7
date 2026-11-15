"""Peer admission and caller-owned routes for the rc.3 Connection candidate."""
import asyncio
import inspect
import json
import re
from types import SimpleNamespace

from dsh.host.connection.current import CurrentHostConnection
from dsh.host.connection.peer import Peer
from dsh.host.connection.rpc_current import rpc_fetch_handler
from dsh.host.connection.rpc_host import endpoint_from_path, response
from dsh.host.connection.trust_current import is_trusted_api_request, is_remote_authority
from dsh.host.connection.auth_current import write_response
from dsh.host.connection.http_current import current_bridge_handler
from dsh.host.connection.http_bridge import DEFAULT_MAX_REQUEST_BODY_BYTES


def peer_bridge_handler(connection, api, limit=DEFAULT_MAX_REQUEST_BODY_BYTES, request_scope=None):
    async def handler(request, writer):
        admission = connection.admit(request)
        if 'rejection' in admission:
            from dsh.host.connection.http_bridge import write_response as write_http_response
            status = admission['rejection']
            await write_http_response(writer, dict(status=status, body='unauthorized' if status == 401 else 'forbidden'))
            return
        carrier = SimpleNamespace(request_rejection=lambda _: None)
        fetch = SimpleNamespace(requestBodyMode=api.requestBodyMode,
                                fetch=lambda req: api.fetch(req, admission['peer']))
        async def delegate():
            await current_bridge_handler(carrier, fetch, limit)(request, writer)
        if request_scope is None:
            await delegate()
        else:
            await request_scope(request, writer, delegate)
    handler.defer_body = True
    return handler


class AuthorizedHostConnection(CurrentHostConnection):
    def __init__(self, ctx, trusted_hosts, browser_auth):
        super().__init__(ctx, trusted_hosts, browser_auth)
        self._owner = ctx
        self._admission = dict(disposed=False, peers={})
        self.browserPeer = Peer(ctx, dict(principal=dict(kind='owner')))
        self.allowsRemoteAuthorities = any(is_remote_authority(entry) for entry in trusted_hosts)
        async def dispose():
            self._admission['disposed'] = True
            peers = [self.browserPeer] + [record['peer'] for record in self._admission['peers'].values()]
            self._admission['peers'].clear()
            await asyncio.gather(*(peer.dispose() for peer in peers))
        ctx.effect(lambda: dispose, 'client-connection: Peer scopes')

    def _secure(self):
        server = self._owner.get('webServer')
        return getattr(server, 'protocol', None) == 'https:'

    def _trusted(self, request):
        server = self._owner.get('webServer')
        return is_trusted_api_request(request, self.trusted_hosts, getattr(server, 'host', None), getattr(server, 'protocol', 'http:'))

    def admit(self, request):
        if not self._trusted(request):
            return dict(rejection=403)
        if self._admission['disposed']:
            return dict(rejection=401)
        secure = self._secure()
        if self.browser_auth.is_authenticated(request, secure):
            return dict(peer=self.browserPeer)
        peer_id = self.browser_auth.authenticate_api(request, secure)
        record = self._admission['peers'].get(peer_id)
        return dict(rejection=401) if record is None else dict(peer=record['peer'])

    def request_rejection(self, request):
        return self.admit(request).get('rejection')

    def create_peer(self, options):
        return Peer(self.ctx, options)

    def admit_connection(self, request):
        admission = self.admit(request)
        if 'rejection' in admission:
            return admission
        peer = admission['peer']
        record = self._admission['peers'].get(peer.id)
        if record is None:
            async def release():
                return None
            return dict(peer=peer, release=release)
        if record['ownsSocket']:
            return dict(rejection=409)
        record['ownsSocket'] = True
        released = []
        def release():
            if not released:
                self._admission['peers'].pop(peer.id, None)
                released.append(peer.dispose())
            return released[0]
        return dict(peer=peer, release=release)

    def _publish_peer(self, interactions):
        peer = Peer(self._owner, dict(principal=dict(kind='owner'), interactions=interactions))
        self._admission['peers'][peer.id] = dict(peer=peer, ownsSocket=False)
        return peer.id

    def authorize_connect(self, request, writer):
        if not self._trusted(request) or self._admission['disposed']:
            disposed = self._admission['disposed']
            write_response(writer, 401 if disposed else 403, body='unauthorized' if disposed else 'forbidden')
            return
        self.browser_auth.authorize_connect(request, writer, self._secure(), self._publish_peer)

    def authorize_index(self, request, writer):
        return self.browser_auth.authorize_index(request, writer, self._secure())

    def intercept(self, owner, channel, matches, handler):
        if channel != '/api':
            raise ValueError('connection: invalid shared RPC channel ' + json.dumps(channel))
        entry = dict(matches=matches, fetch=rpc_fetch_handler(channel, handler).fetch)
        def setup():
            if channel in self.interceptors:
                raise ValueError('connection: shared RPC channel ' + json.dumps(channel) + ' already has an interceptor')
            self.interceptors[channel] = entry
            return lambda: self.interceptors.pop(channel, None)
        return owner.effect(setup, 'client-connection: {} RPC interceptor'.format(channel))

    def create_shared_fetch_handler(self, channel):
        modes = super().create_shared_fetch_handler(channel)
        async def fetch(request, peer):
            route = self.fetch_routes.get(request['path'])
            if route is not None and request['method'] in route['methods']:
                if peer.principal['kind'] != 'owner':
                    return response(403, 'forbidden')
                value = route['fetch'](request)
                return await value if inspect.isawaitable(value) else value
            endpoint = endpoint_from_path(channel, request['path'])
            interceptor = self.interceptors.get(channel)
            if endpoint is None or interceptor is None or not interceptor['matches'](endpoint):
                return response(404, 'not found')
            return await interceptor['fetch'](request, peer)
        return SimpleNamespace(requestBodyMode=modes.requestBodyMode, fetch=fetch)

    def register(self, owner, channel, handler):
        if channel == '/api' or not re.fullmatch(r'/[A-Za-z0-9._~-]+', channel):
            raise ValueError('connection: invalid or reserved RPC channel ' + json.dumps(channel))
        carrier = peer_bridge_handler(self, rpc_fetch_handler(channel, handler))
        return owner.effect(lambda: owner.get('webServer').register('prefix', channel, carrier), 'client-connection: {} rpc channel'.format(channel))

    requestRejection = request_rejection
    createPeer = create_peer
    admitConnection = admit_connection
    authorizeConnect = authorize_connect
    authorizeIndex = authorize_index
    createSharedFetchHandler = create_shared_fetch_handler
