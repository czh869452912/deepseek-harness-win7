"""Candidate WebServer index contract: every document speaks for one Peer."""
from dsh.host.webserver.webserver import WebServerService
from dsh.host.webserver.injections import render_index_injections


class CurrentWebServer(WebServerService):
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
