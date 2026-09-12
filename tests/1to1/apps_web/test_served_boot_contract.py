"""
Served boot contract of the built `@deepseek-ai/dsh-web-frontend` payload.

`apps/web/dist` is not served on its own: the shipped entry chunk
(`assets/index-*.js`, the vite build of `apps/web/src/main.ts`) reads the
globals a boot protocol injects ahead of it and refuses to run without them
(`web boot: window.__ModuleLoader__ bootstrap facade is missing`). Upstream
renders that document from one injection table — the rows
`reference/packages/client/modules/src/index.ts` `bootInjections` contributes,
rendered by `reference/packages/host/webserver/src/injections.ts`
`renderIndexInjections`:

  head: the inline registration queue facade, the parser-preload scripts, the
        `__DSH_BOOT__` graph global;
  body: the boot-readiness tail that settles `__DSH_BOOT_READY__`, which
        `reference/packages/client/web/src/boot.ts` awaits before reading any
        injected state.

These cases drive the port's real seats (`WebServerService` + the
client-modules index tap + the frontend-static fallback) over the real built
payload, so a served shell that cannot boot fails here instead of in a browser.
"""

import asyncio
import hashlib
import json
import os
import re

import pytest

from dsh.cordis.context import Context
from dsh.host.client_modules.registry import (
    CLIENT_MODULES_ID,
    ClientModulesPlugin,
)
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.webserver.injections import READY_MARKUP, render_index_injections
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DIST_ROOT = os.path.join(REPO_ROOT, "apps", "web", "dist")

# Upstream `bootInjections` failure contract, verbatim.
FACADE_AFTER_BOOT = "client-modules: window.__ModuleLoader__.create called after module-system boot"
FACADE_MISSING_PRELOAD = "client-modules: HTML did not preload @deepseek-ai/dsh-client-modules/client.js"
FACADE_WRONG_FACE = "client-modules: @deepseek-ai/dsh-client-modules/client.js did not export the bootstrap module face"
# The built entry chunk's own refusal, read out of the shipped bytes below.
ENTRY_MISSING_FACADE = "web boot: window.__ModuleLoader__ bootstrap facade is missing"


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
    ctx.plugin(ClientModulesPlugin)
    ctx.plugin(FrontendStaticPlugin)
    return ctx


def entry_chunk_path():
    """The entry module chunk the built document loads."""
    index = os.path.join(DIST_ROOT, "index.html")
    html = open(index, "r", encoding="utf-8").read()
    match = re.search(r'<script type="module"[^>]*\bsrc="\./([^"]+)"', html)
    assert match is not None, "built document carries no entry module script"
    return os.path.join(DIST_ROOT, match.group(1).replace("/", os.sep))


def entry_chunk():
    return open(entry_chunk_path(), "r", encoding="utf-8", errors="replace").read()


async def served_index(ctx):
    """Render the served document through the real seat chain."""
    server = ctx.get("web_server")
    fallback = server._fallback
    assert fallback is not None, "frontend-static claimed no fallback seat"
    request = {"method": "GET", "path": "/", "query": "", "headers": {}, "body": b""}
    response = HttpResponseWriter(RecordingStream())
    await fallback(request, response)
    assert response.status == 200
    return bytes(response.body).decode("utf-8")


def boot_graph(body):
    match = re.search(r"window\.__DSH_BOOT__ = (\{.*?\});</script>", body, re.DOTALL)
    assert match is not None, "served index carries no boot graph"
    return json.loads(match.group(1))


def entry_script_offset(body):
    match = re.search(r'<script type="module"[^>]*\bsrc="\./assets/', body)
    assert match is not None, "served index carries no entry module script"
    return match.start()


@pytest.mark.asyncio
async def test_the_built_entry_demands_the_facade_the_served_index_provides(served_web):
    """The requirement is read out of the shipped bytes, not restated from the port."""
    chunk = entry_chunk()
    assert ENTRY_MISSING_FACADE in chunk, "entry chunk no longer refuses a bootless shell"
    assert "__DSH_BOOT_READY__" in chunk, "entry chunk no longer awaits the boot-readiness deferred"
    assert "boot:" in chunk, "entry chunk no longer hands the injector a boot graph"

    body = await served_index(served_web)
    entry_at = entry_script_offset(body)
    facade_at = body.find("window.__ModuleLoader__={")
    graph_at = body.find("window.__DSH_BOOT__ = ")
    assert facade_at != -1, "served index carries no registration queue facade"
    assert graph_at != -1, "served index carries no boot graph global"
    # Both globals are plain parser-order siblings of the (deferred) entry
    # module, so their position ahead of it is what makes them readable.
    assert facade_at < entry_at
    assert graph_at < entry_at


@pytest.mark.asyncio
async def test_queue_facade_carries_the_upstream_failure_contract(served_web):
    """The facade is the only seat that can report these failures at boot."""
    body = await served_index(served_web)
    assert FACADE_AFTER_BOOT in body
    assert FACADE_MISSING_PRELOAD in body
    assert FACADE_WRONG_FACE in body
    # The bootstrap face is what the shell constructs the module system from:
    # `createClientModuleSystem` builds it, `apply` installs it as a plugin.
    assert 'typeof exports.createClientModuleSystem!=="function"' in body
    assert 'typeof exports.apply!=="function"' in body
    assert "return exports.createClientModuleSystem(this,{id:registration.id,exports},options);" in body


@pytest.mark.asyncio
async def test_parser_preload_bundle_is_blocking_and_ahead_of_the_shell(served_web):
    """The module-system bundle must have registered itself before the shell runs."""
    body = await served_index(served_web)
    graph = boot_graph(body)
    modules = [entry for entry in graph["entries"] if entry["id"] == CLIENT_MODULES_ID]
    assert len(modules) == 1, "the shipped roster carries exactly one module-system row"
    url = modules[0]["url"]

    match = re.search(r'<script src="([^"]*%s[^"]*)"' % re.escape(CLIENT_MODULES_ID), body)
    assert match is not None, "served index carries no parser-preload script for the module-system bundle"
    assert match.group(1) == url
    # Parser-blocking: a module/defer/async script would execute after the entry.
    assert match.group(0) == '<script src="%s"' % url
    assert match.start() < entry_script_offset(body)
    assert match.start() > body.find("window.__ModuleLoader__={")
    assert modules[0]["rev"] != "0" * 12


@pytest.mark.asyncio
async def test_served_body_settles_the_boot_readiness_deferred(served_web):
    """
    The tail resolves the deferred the entry awaits, in one statement.

    `Promise.withResolvers` is the upstream spelling and no browser available on
    Windows 7 provides it (Firefox ESR 115 is the newest that runs there), so
    the served build constructs the same deferred inline.
    """
    body = await served_index(served_web)
    assert READY_MARKUP in body
    assert "Promise.withResolvers" not in body
    assert "globalThis.__DSH_BOOT_READY__" in body
    # Settled in the body, i.e. after the document's head rows are defined.
    assert body.find(READY_MARKUP) > body.index("<body>")
    assert body.find(READY_MARKUP) > body.find("window.__DSH_BOOT__ = ")


def test_application_preload_rows_render_as_preload_links():
    """
    The application tier is advertised, not executed.

    Upstream `bootInjections` emits one `script-preload` row per application
    batch, which `renderIndexInjections` renders as
    `<link rel="preload" as="script" href=...>`; only the parser tier is a
    blocking `<script src>`. The port's injection table must keep that
    distinction, because a preload row rendered as a script would execute a
    client bundle before the facade exists.
    """
    html = "<html><head><title>t</title></head><body><div id='root'></div></body></html>"
    out = render_index_injections(html, [
        {"kind": "script-preload", "src": "/plugins/??a/client.js&rev=abc"},
        {"kind": "script-src", "placement": "head", "src": "/plugins/??b/client.js&rev=def"},
    ])
    assert '<link rel="preload" as="script" href="/plugins/??a/client.js&amp;rev=abc">' in out
    assert '<script src="/plugins/??b/client.js&amp;rev=def"></script>' in out
    assert out.index('<link rel="preload"') < out.index("<script src=")
    assert READY_MARKUP in out
    # The tail is settled after every body row, and an empty table still settles
    # it: a page with no boot rows must not leave the entry awaiting forever.
    headless = render_index_injections("<div id='root'></div>", [])
    assert headless.endswith(READY_MARKUP)


@pytest.mark.asyncio
async def test_served_graph_is_the_shipped_client_roster(served_web):
    """
    The graph advertises exactly the browser plugins the shipped profile mounts.

    Upstream composes `window.__DSH_BOOT__` from the `dsh.client` declarations of
    the Loader rows the profile activated, so the roster is a composition fact,
    not a directory listing: an extra entry mounts a plugin no shipped profile
    asked for, and a missing entry leaves a UI the lane drives unregistered. The
    two bundles the `web` profile composes are named here directly, so the check
    is against the shipped composition rather than against the port's own scan.
    """
    import json

    def package_of(name):
        parts = name.split("/")
        return "/".join(parts[:2]) if name.startswith("@") else parts[0]

    shipped = set()
    for bundle in ("base", "web-app"):
        document = os.path.join(REPO_ROOT, "reference", "packages", "bundle", bundle, "cordis.patch.yml")
        assert os.path.isfile(document), document
        text = open(document, "r", encoding="utf-8").read()
        for name in re.findall(r"^\s*-?\s*id:\s*[\w@/.-]+\s*\n\s*name:\s*'([^']+)'", text, re.M):
            package = package_of(name)
            manifest = mirrored_client_manifest(package)
            if manifest is not None:
                shipped.add(package)
    assert len(shipped) > 40, "the shipped client roster did not resolve"

    graph = boot_graph(await served_index(served_web))
    served = {entry["id"] for entry in graph["entries"]}
    assert served == shipped


def mirrored_client_manifest(package):
    """The `package.json` of a mirrored package that declares a `dsh.client` half."""
    import json

    root = os.path.join(REPO_ROOT, "packages")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("lib", "node_modules", "tests")]
        if "package.json" not in filenames:
            continue
        manifest = json.load(open(os.path.join(dirpath, "package.json"), "r", encoding="utf-8"))
        if manifest.get("name") == package and "client" in (manifest.get("dsh") or {}):
            return os.path.join(dirpath, "package.json")
    return None


@pytest.mark.asyncio
async def test_every_advertised_client_bundle_is_served_over_a_real_socket(served_web):
    """The whole advertised graph is fetchable: an unserved row is a dead preload."""
    server = served_web.get("web_server")
    await server.start()
    try:
        port = server.listened_port
        status, _, body_bytes = await raw_get(port, "/")
        assert status == 200
        body = body_bytes.decode("utf-8")
        graph = boot_graph(body)

        urls = [entry["url"] for entry in graph["entries"]]
        assert len(urls) > 30, "the shipped roster is not a hand-picked subset"
        for entry in graph["entries"]:
            status, headers, payload = await raw_get(port, entry["url"])
            assert status == 200, entry["id"]
            assert "javascript" in headers.get("content-type", ""), entry["id"]
            # The bundle registers itself through the facade the index defines,
            # under the id the graph advertises.
            assert b"__ModuleLoader__.load(" in payload, entry["id"]
            assert ('"%s"' % entry["id"]).encode("utf-8") in payload, entry["id"]
            # Versioned bytes are immutable: the rev in the URL is the hash of
            # what the route serves.
            assert entry["rev"] == hashlib.sha1(payload).hexdigest()[:12], entry["id"]
    finally:
        await server.stop()


async def raw_get(port, path):
    """One real HTTP/1.1 request against the bound server."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" % path).encode("ascii"))
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        status_line, _, raw_headers = head.partition(b"\r\n")
        status = int(status_line.split(b" ")[1])
        headers = {}
        for line in raw_headers.decode("latin-1").split("\r\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()
        body = await reader.read()
        return status, headers, body
    finally:
        writer.close()
