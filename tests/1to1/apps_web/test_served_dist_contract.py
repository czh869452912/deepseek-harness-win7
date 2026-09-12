"""
Serving contract for the built `@deepseek-ai/dsh-web-frontend` payload.

Upstream owns the dist (`apps/web/dist`) and asserts its shipped bytes in
`reference/apps/web/tests/pwa-manifest.e2e.ts`; the *served* form of that
payload is the SPA seat (`@deepseek-ai/dsh-host-frontend-static`) plus the
client-module boot manifest (`@deepseek-ai/dsh-client-modules`), which
`reference/apps/web/tests/vite-entry.e2e.ts` guards from the other side: a
shell served without `window.__DSH_BOOT__` must never be presented as a working
GUI.

These cases wire the Python port's real seats over the real `apps/web/dist`
payload and observe the fallback HTTP surface, so the ported upstream
assertions (`dist/index.html` shape, install metadata bytes, `__DSH_BOOT__`
injection) hold over the served response rather than only over the file.
"""

import json
import os
import re
import pytest

from dsh.cordis.context import Context
from dsh.host.client_modules.registry import ClientModulesPlugin
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DIST_ROOT = os.path.join(REPO_ROOT, "apps", "web", "dist")

EXPECTED_MANIFEST = {
    "id": "/",
    "name": "DeepSeek Harness",
    "short_name": "DSH",
    "start_url": "/",
    "scope": "/",
    "display": "fullscreen",
    "icons": [
        {
            "src": "/favicon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any",
        }
    ],
}


class RecordingStream:
    """Minimal asyncio stream writer standing in for the socket."""

    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass


@pytest.fixture
def served_web():
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("web_server", server)
    # The client-module seat owns the boot manifest injection; the frontend seat
    # owns the fallback that serves the dist.
    ctx.plugin(ClientModulesPlugin)
    ctx.plugin(FrontendStaticPlugin)
    return ctx


async def _request(ctx, path, method="GET"):
    server = ctx.get("web_server")
    fallback = server._fallback
    assert fallback is not None, "frontend-static claimed no fallback seat"
    request = {"method": method, "path": path, "query": "", "headers": {}, "body": b""}
    response = HttpResponseWriter(RecordingStream())
    await fallback(request, response)
    return response


def _body_text(response):
    return bytes(response.body).decode("utf-8")


@pytest.mark.asyncio
async def test_served_index_carries_dist_markup_and_the_boot_manifest(served_web):
    response = await _request(served_web, "/")
    assert response.status == 200
    assert response.headers.get("Content-Type") == "text/html; charset=utf-8"
    body = _body_text(response)
    assert '<div id="root"></div>' in body
    # vite-entry.e2e.ts's invariant: a shell without the boot manifest is not a
    # working GUI. The served page must carry the composed client boot graph.
    assert "window.__DSH_BOOT__" in body


@pytest.mark.asyncio
async def test_served_install_metadata_matches_the_shipped_manifest(served_web):
    response = await _request(served_web, "/manifest.webmanifest")
    assert response.status == 200
    assert response.headers.get("Content-Type") == "application/manifest+json"
    assert json.loads(_body_text(response)) == EXPECTED_MANIFEST


@pytest.mark.asyncio
async def test_served_favicon_keeps_its_dark_scheme_mark(served_web):
    response = await _request(served_web, "/favicon.svg")
    assert response.status == 200
    assert response.headers.get("Content-Type") == "image/svg+xml"
    body = _body_text(response)
    assert re.search(
        r"@media \(prefers-color-scheme: dark\)\s*{\s*path\s*{[^}]*fill:\s*#fff",
        body,
        re.IGNORECASE,
    ) is not None
    assert 'fill="#000"' in body


@pytest.mark.asyncio
async def test_served_entry_script_is_the_built_chunk(served_web):
    index = await _request(served_web, "/")
    urls = re.findall(r'<script[^>]*\bsrc="\./([^"]+)"', _body_text(index))
    assert urls, "served index carries no entry script"
    for url in urls:
        response = await _request(served_web, "/" + url)
        assert response.status == 200, url
