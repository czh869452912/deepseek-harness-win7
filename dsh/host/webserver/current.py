"""Candidate WebServer index contract: every document speaks for one Peer."""
from dsh.host.webserver.webserver import WebServerService
from dsh.host.webserver.injections import render_index_injections
from dsh.host.webserver.resources import invoke, request_path, request_target, resource_handler, without_body
from urllib.parse import urlsplit
from dsh.core.abort import NEVER_ABORTED


class CurrentWebServer(WebServerService):
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
