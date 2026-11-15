"""Candidate Connection plugin mounting authenticated API and connect routes."""
import math

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.host.connection.api_trust import assert_trusted_authority
from dsh.host.connection.auth_current import CurrentBrowserAuth
from dsh.host.connection.authorized import AuthorizedHostConnection, peer_bridge_handler
from dsh.host.connection.current import ConnectionRecoveryConfigSchema, resolve_connection_config
from dsh.host.connection.http_bridge import DEFAULT_MAX_REQUEST_BODY_BYTES


class AuthorizedConnectionPlugin(Plugin):
    id = 'client-connection'
    inject = ['credentials']
    Config = z.object(dict(
        recovery=ConnectionRecoveryConfigSchema.default({}),
        trustedHosts=z.array(z.string()).default([]),
        cookieMaxAgeDays=z.natural().min(1).default(30),
        maxRequestBodyBytes=z.natural().min(1).default(DEFAULT_MAX_REQUEST_BODY_BYTES)))

    def apply(self, ctx):
        config = self.config
        recovery = resolve_connection_config(config.get('recovery', _UNDEFINED))
        trusted = config.get('trustedHosts', [])
        days = config.get('cookieMaxAgeDays', 30)
        limit = config.get('maxRequestBodyBytes', DEFAULT_MAX_REQUEST_BODY_BYTES)
        for entry in trusted:
            assert_trusted_authority(entry)
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
        connection = AuthorizedHostConnection(ctx, trusted, CurrentBrowserAuth.create(ctx.root, ctx.get('credentials'), days))
        def web(child):
            capacity(child)
            child.on('webserver/index-inject', lambda table, *args: table.append(dict(kind='global', name='__DSH_CONNECTION_RECOVERY__', value=recovery)))
            handler = peer_bridge_handler(connection, connection.create_shared_fetch_handler('/api'), limit,
                lambda request, writer, next_fn: child.waterfall('connection/request', request, writer, next_fn))
            child.effect(lambda: child.get('webServer').register('prefix', '/api', handler), 'client-connection: /api route')
            async def connect(request, writer):
                connection.authorize_connect(request, writer)
                await writer.finish()
            child.effect(lambda: child.get('webServer').register('exact', '/connect', connect), 'client-connection: /connect route')
        ctx.inject(['webServer'], web)
        ctx.inject(['attachments'], capacity)
