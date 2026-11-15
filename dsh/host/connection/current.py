"""rc.3 carrier-neutral Connection registry and optional HTTP carrier."""
import inspect
import math
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.host.connection.api_trust import assert_trusted_authority
from dsh.host.connection.browser_auth import BrowserAuth
from dsh.host.connection.rpc_host import HostConnectionService, endpoint_from_path, response, rpc_fetch
from dsh.host.connection.http_bridge import DEFAULT_MAX_REQUEST_BODY_BYTES
from dsh.host.connection.http_current import current_bridge_handler


ConnectionRecoveryConfigSchema = z.object(dict(
    backoffBaseMs=z.natural().min(1).max(2147483647).default(500),
    backoffFactor=z.number().min(1).max(float.fromhex('0x1.fffffffffffffp+1023')).default(2),
    backoffMaxMs=z.natural().min(1).max(2147483647).default(10000),
    generationReadyWarnMs=z.natural().min(1).max(2147483647).default(3000),
    generationReadyTimeoutMs=z.natural().min(1).max(2147483647).default(15000)))


def resolve_connection_config(config=_UNDEFINED):
    resolved = ConnectionRecoveryConfigSchema({} if config is _UNDEFINED else config)
    if not math.isfinite(resolved['backoffFactor']):
        raise ValueError('connection recovery backoffFactor must be finite')
    return resolved


async def current_rpc_fetch(channel, handler, request):
    return await rpc_fetch(channel, handler, request, 'gateway/bad-request',
                           lambda error: getattr(error, 'name', 'Error') + ': ' + str(error), True)


class CurrentHostConnection(HostConnectionService):
    def register_fetch(self, owner, route):
        path = route['path']
        if endpoint_from_path('/api', path) is None:
            raise ValueError('connection: invalid exact Fetch route ' + json.dumps(path))
        if not route['methods']:
            raise ValueError('connection: exact Fetch route ' + json.dumps(path) + ' declares no methods')
        if len(set(route['methods'])) != len(route['methods']):
            raise ValueError('connection: exact Fetch route ' + json.dumps(path) + ' repeats a method')
        entry = dict(methods=set(route['methods']), requestBody=route['requestBody'], fetch=route['fetch'])
        def setup():
            if path in self.fetch_routes:
                raise ValueError('connection: exact Fetch route ' + json.dumps(path) + ' is already registered')
            self.fetch_routes[path] = entry
            return lambda: self.fetch_routes.pop(path, None)
        return owner.effect(setup, 'Connection Fetch route')

    def create_shared_fetch_handler(self, channel):
        def body_mode(request):
            path = request.get('path')
            if path is None:
                path = urlsplit(str(request['url'])).path
            route = self.fetch_routes.get(path)
            return route['requestBody'] if route is not None and request['method'] in route['methods'] else 'buffered'
        async def fetch(request):
            route = self.fetch_routes.get(request['path'])
            if route is not None and request['method'] in route['methods']:
                result = route['fetch'](request)
                return await result if inspect.isawaitable(result) else result
            endpoint = endpoint_from_path(channel, request['path'])
            interceptor = self.interceptors.get(channel)
            if endpoint is None or interceptor is None or not interceptor['matches'](endpoint):
                return response(404, 'not found', {'content-type': 'text/plain;charset=UTF-8'})
            return await current_rpc_fetch(channel, interceptor['handler'], request)
        return SimpleNamespace(fetch=fetch, requestBodyMode=body_mode)

    createSharedFetchHandler = create_shared_fetch_handler

    def register(self, owner, channel, handler):
        import re
        if channel == '/api' or not re.fullmatch(r'/[A-Za-z0-9._~-]+', channel):
            raise ValueError('connection: invalid or reserved RPC channel ' + json.dumps(channel))
        async def fetch(request):
            return await current_rpc_fetch(channel, handler, request)
        api = SimpleNamespace(fetch=fetch, requestBodyMode=lambda _: 'buffered')
        return owner.effect(lambda: owner.get('webServer').register('prefix', channel, current_bridge_handler(self, api)),
                            'Connection rpc channel')


class CurrentConnectionPlugin(Plugin):
    id = 'client-connection'
    inject = ['credentials']

    def apply(self, ctx):
        recovery = resolve_connection_config(self.config.get('recovery', _UNDEFINED))
        trusted = self.config.get('trustedHosts', [])
        days = self.config.get('cookieMaxAgeDays', 30)
        limit = self.config.get('maxRequestBodyBytes', DEFAULT_MAX_REQUEST_BODY_BYTES)
        for authority in trusted:
            assert_trusted_authority(authority)
        def capacity(child):
            attachments = child.get('attachments')
            if attachments is None:
                return
            limits = getattr(attachments, 'imageLimits', None) or attachments.image_limits
            maximum = limits['maxMessageImageBytes'] if isinstance(limits, dict) else limits.maxMessageImageBytes
            required = math.ceil(maximum * 4 / 3) + 1024 * 1024
            if limit < required:
                raise ValueError('client-connection maxRequestBodyBytes ({}) must be at least {} for the configured aggregate image limit'.format(limit, required))
        capacity(ctx)
        connection = CurrentHostConnection(ctx, trusted, BrowserAuth.create(ctx.root, ctx.get('credentials'), days))
        def web(child):
            capacity(child)
            child.on('webserver/index-inject', lambda table, *peer: table.append(dict(kind='global', name='__DSH_CONNECTION_RECOVERY__', value=recovery)))
            handler = current_bridge_handler(connection, connection.create_shared_fetch_handler('/api'), limit)
            child.effect(lambda: child.get('webServer').register('prefix', '/api', handler), 'Connection /api route')
        ctx.inject(['webServer'], web)
        ctx.inject(['attachments'], capacity)
