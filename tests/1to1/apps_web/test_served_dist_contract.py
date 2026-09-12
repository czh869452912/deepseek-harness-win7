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
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.host.client_modules.registry import ClientModulesPlugin
from dsh.host.connection.connection import ConnectionPlugin
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEB_ROOT = os.path.join(REPO_ROOT, "apps", "web")
DIST_ROOT = os.path.join(WEB_ROOT, "dist")

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
def served_web(tmp_path):
    ctx = Context()
    server = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("web_server", server)
    # The shipped Web composition: the credentials store, the connection owner
    # (browser authentication plus the /api fence), the client-module seat that
    # owns the boot manifest injection, and the frontend seat that owns the
    # authenticated fallback serving the dist.
    ctx.plugin(CredentialsLocalPlugin, config={"path": str(tmp_path / ".credentials.yaml"), "watch": False})
    ctx.plugin(ClientModulesPlugin)
    ctx.plugin(ConnectionPlugin)
    ctx.plugin(FrontendStaticPlugin)
    return ctx


async def _authenticated_cookie(ctx):
    """Run the launch-token exchange the browser performs on its first navigation."""
    server = ctx.get("web_server")
    fallback = server._fallback
    connection = ctx.get("connection")
    url = connection.authenticated_url("http://127.0.0.1")
    token = url.split("token=", 1)[1]
    request = {
        "method": "GET",
        "path": "/",
        "query": "token=" + token,
        "raw_url": "/?token=" + token,
        "headers": {"host": "127.0.0.1"},
        "body": b"",
    }
    response = HttpResponseWriter(RecordingStream())
    await fallback(request, response)
    assert response.status == 303, "launch-token exchange did not redirect"
    return response.headers["set-cookie"].split(";", 1)[0]


async def _request(ctx, path, method="GET"):
    server = ctx.get("web_server")
    fallback = server._fallback
    assert fallback is not None, "frontend-static claimed no fallback seat"
    cookie = await _authenticated_cookie(ctx)
    pathname, _, query = path.partition("?")
    request = {
        "method": method,
        "path": pathname,
        "query": query,
        "raw_url": path,
        "headers": {"host": "127.0.0.1", "cookie": cookie},
        "body": b"",
    }
    response = HttpResponseWriter(RecordingStream())
    await fallback(request, response)
    return response


def _body_text(response):
    return bytes(response.body).decode("utf-8")


@pytest.mark.asyncio
async def test_served_index_carries_dist_markup_and_the_boot_manifest(served_web):
    response = await _request(served_web, "/")
    assert response.status == 200
    assert response.headers.get("content-type") == "text/html; charset=utf-8"
    body = _body_text(response)
    assert '<div id="root"></div>' in body
    # vite-entry.e2e.ts's invariant: a shell without the boot manifest is not a
    # working GUI. The served page must carry the composed client boot graph.
    assert "window.__DSH_BOOT__" in body


@pytest.mark.asyncio
async def test_served_install_metadata_matches_the_shipped_manifest(served_web):
    response = await _request(served_web, "/manifest.webmanifest")
    assert response.status == 200
    assert response.headers.get("content-type") == "application/manifest+json"
    assert json.loads(_body_text(response)) == EXPECTED_MANIFEST


@pytest.mark.asyncio
async def test_served_favicon_keeps_its_dark_scheme_mark(served_web):
    response = await _request(served_web, "/favicon.svg")
    assert response.status == 200
    assert response.headers.get("content-type") == "image/svg+xml"
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


@pytest.mark.asyncio
async def test_served_index_carries_the_composed_boot_graph_from_any_cwd(served_web, tmp_path, monkeypatch):
    """The boot graph is composed from the application root, not the caller cwd."""
    monkeypatch.chdir(str(tmp_path))
    body = _body_text(await _request(served_web, "/"))
    match = re.search(r"window\.__DSH_BOOT__ = (\{.*?\});</script>", body, re.DOTALL)
    assert match is not None, "served index carries no boot manifest"
    graph = json.loads(match.group(1))
    ids = [entry["id"] for entry in graph["entries"]]
    # The whole shipped roster, not an empty graph: an unresolved graph injects
    # no preload and the served shell cannot boot.
    assert len(ids) > 30
    assert "@deepseek-ai/dsh-client-modules" in ids
    for entry in graph["entries"]:
        assert entry["rev"] != "000000000000", entry["id"]
    assert '<script src="/plugins/@deepseek-ai/dsh-client-modules/client.js?rev=' in body


def test_spa_seat_resolves_the_built_dist_not_the_source_document():
    """The seat's root is the vite output; the source document is never served."""
    plugin = FrontendStaticPlugin()
    assert plugin.dist_index == os.path.join(DIST_ROOT, "index.html")
    assert plugin.dist_root == DIST_ROOT
    # The source document exists in the mirrored package and is deliberately not
    # a candidate: it names `/src/main.ts`, which no browser executes.
    source_document = os.path.join(WEB_ROOT, "index.html")
    assert os.path.isfile(source_document)
    assert "src/main.ts" in open(source_document, "r", encoding="utf-8").read()
    assert plugin.dist_index != source_document


@pytest.mark.asyncio
async def test_served_index_is_the_built_document(served_web):
    """The served page is `dist/index.html`, never the package source document."""
    body = _body_text(await _request(served_web, "/"))
    assert "/src/" not in body
    assert re.search(r'<script type="module" crossorigin src="\./assets/[^"]+\.js"></script>', body) is not None
