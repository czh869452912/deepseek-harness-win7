"""Candidate WebServer index contract: every document speaks for one Peer."""
from dsh.host.webserver.webserver import WebServerService
from dsh.host.webserver.injections import render_index_injections
from dsh.host.webserver.resources import invoke, request_path, request_target, resource_handler, without_body
from urllib.parse import urlsplit
from dsh.core.abort import NEVER_ABORTED
import json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.host.webserver.bind import validate_host, bind_url_host
from dsh.host.webserver.tls import prepare_tls


CONFIG = z.object(dict(
    host=z.transform(z.string(), validate_host).required(),
    port=z.natural().max(65535).required(),
    tls=z.object(dict(certFile=z.string().required(), keyFile=z.string().required())).default(None),
    compression=z.union([z.const('none'), z.const('gzip')]).default('none'),
    compressionLevel=z.number().step(1).min(0).max(9).default(1),
    compressionThresholdBytes=z.natural().default(1024),
))


class CurrentWebServer(WebServerService):
    Config = CONFIG

    def __init__(self, ctx, host='127.0.0.1', port=8080, tls=None, **kwargs):
        validate_host(host)
        super().__init__(ctx, host=host, port=port, **kwargs)
        self.listened_port = None
        self.configured_port = port
        self.port = None
        self.tls = tls
        self.ssl_context = None

    def bind_port(self):
        return self.configured_port

    @property
    def protocol(self):
        return 'https:' if self.tls is not None else 'http:'

    def get_origin(self):
        host = bind_url_host(self.host)
        if host is None:
            raise ValueError('webserver: bind address {} carries an interface zone id, which no URL can express'.format(json.dumps(self.host)))
        if self.listened_port is None:
            raise ValueError('webserver: origin read before the listener bound a port')
        return '{}//{}:{}'.format(self.protocol, host, self.listened_port)

    async def start(self):
        if self._is_running:
            return
        if self.tls is not None:
            self.ssl_context = await prepare_tls(self.tls)
        await super().start()

    async def stop(self):
        # Node destroys connections at unload. SSL close_notify can otherwise
        # wait indefinitely for an uncooperative peer on Python 3.8.
        if self.tls is not None:
            for writer in list(self._connections) + list(self._upgraded_sockets):
                self._destroy_socket(writer)
        await super().stop()

    getOrigin = get_origin

    def parse_request_target(self, value):
        return urlsplit(request_target(value))

    def register(self, kind, path=None, handler=None):
        if isinstance(kind, dict):
            route = kind
            kind, path = route['kind'], route['path']
            handler = resource_handler(route['resource']) if 'resource' in route else route['handler']
        return super().register(kind, path, handler)

    def register_fallback(self, handler):
        if isinstance(handler, dict):
            handler = resource_handler(handler['resource'])
        return super().register_fallback(handler)

    async def read_resource(self, request, peer):
        if request.get('method', 'GET') not in ('GET', 'HEAD'):
            return dict(status=405, headers=dict(allow='GET, HEAD'), body=None)
        route = self.match(request_path(request))
        responder = route.handler if route is not None else self._fallback
        resource = getattr(responder, 'resource', None)
        if resource is None:
            return dict(status=404, headers={}, body=None)
        request = dict(request, method=request.get('method', 'GET'), headers=request.get('headers', {}),
                       signal=request.get('signal', NEVER_ABORTED),
                       url=request_target(request.get('url', request.get('path', '/'))))
        response = await invoke(resource, request, peer)
        return await without_body(response) if request.get('method') == 'HEAD' else response

    def collect_index_injections(self, peer):
        table = []
        self.ctx.emit('webserver/index-inject', table, peer)
        return table

    def render_index(self, html, peer):
        injected = render_index_injections(html, self.collect_index_injections(peer))
        rendered = self.apply_index_taps(injected)
        compatibility = self.ctx.get('browserCompatibility')
        return compatibility.validate_index(rendered) if compatibility is not None else rendered

    collectIndexInjections = collect_index_injections
    renderIndex = render_index
    readResource = read_resource
    registerFallback = register_fallback


class CurrentWebServerPlugin(Plugin):
    id = 'webserver'
    name = '@deepseek-ai/dsh-host-webserver'
    Config = CONFIG

    async def apply(self, ctx):
        cfg = self.config
        server = CurrentWebServer(ctx, host=cfg['host'], port=cfg['port'], tls=cfg.get('tls'),
                                  compression=cfg['compression'], compression_level=cfg['compressionLevel'],
                                  compression_threshold_bytes=cfg['compressionThresholdBytes'])
        ctx.set_service('web_server', server)
        ctx.set_service('webServer', server)
        async def acquire():
            await server.start()
            return server.stop
        await ctx.effect(acquire, 'webServer.listen')
