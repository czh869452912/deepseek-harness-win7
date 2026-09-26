"""
SPA dist server over the webserver fallback seat (`@deepseek-ai/dsh-host-frontend-static`).

1:1 port of `reference/packages/host/frontend-static/src/index.ts`: serves the
built frontend directory with explicit index entry points. A readable index
renders at the dist root and the configured index path; missing paths return an
empty 404, traversal outside the dist root is 403, unknown extensions ship as
octet-stream, and non-GET/HEAD is 405. Every index response first passes
Connection's browser authentication, then the webserver's index render
(structured injection rows, then raw taps). Non-index assets stay public. The
dist location is workspace knowledge of the composing application, so
`distIndex` is supplied by configuration.
"""

import os
import re
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

HTML_MIME = "text/html; charset=utf-8"

MIME_TYPES: Dict[str, str] = {
    ".html": HTML_MIME,
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    # The packed VFS image. Served as its own bytes, never as a
    # Content-Encoding: the worker inflates the body itself.
    ".gz": "application/gzip",
}

# Only absent or non-file targets are 404. Python raises FileNotFoundError
# (ENOENT) / NotADirectoryError (ENOTDIR); a directory target raises
# IsADirectoryError on POSIX and PermissionError (EACCES) on Windows 7, so the
# directory case is classified explicitly in `serve_static` and the EISDIR
# family is kept here for the POSIX arm.
STATIC_MISS_ERRORS = (FileNotFoundError, IsADirectoryError, NotADirectoryError)

_HEAD_OPEN = re.compile(r"<head(?:\s[^>]*)?>", re.IGNORECASE)


class FrontendStaticPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-frontend-static`: authenticated SPA dist server.
    """

    id = "frontend-static"
    name = "@deepseek-ai/dsh-host-frontend-static"
    inject = ["web_server", "connection"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        # The seat serves the BUILT application (`apps/web/dist`, the vite output).
        # The source document (`apps/web/index.html`) is deliberately not a
        # candidate: it names `/src/main.ts`, which no browser executes, so
        # serving it would present exactly the bootless shell
        # `apps/web/tests/vite-entry.e2e.ts` forbids.
        candidates = [
            os.path.join(repo_root, "apps", "web", "dist", "index.html"),
            os.path.join(repo_root, "reference", "apps", "web", "dist", "index.html"),
        ]
        chosen = cfg.get("distIndex")
        if not chosen:
            for c in candidates:
                if os.path.isfile(c):
                    chosen = c
                    break
        self.dist_index = os.path.normpath(os.path.abspath(chosen or candidates[0]))
        self.dist_root = os.path.dirname(self.dist_index)

    async def render_index(self, web_server: WebServerService) -> str:
        """Read the configured index and project it into its served form."""
        with open(self.dist_index, "r", encoding="utf-8") as handle:
            body = handle.read()
        rendered = web_server.render_index(body)
        # The dist is built with a relative base so the same files mount under
        # any static directory; served pages also answer deep SPA-fallback
        # paths, where relative asset URLs would resolve under the request
        # directory, so the served form anchors them at the site root ahead of
        # every URL-bearing tag.
        return _HEAD_OPEN.sub(lambda match: match.group(0) + '<base href="/">', rendered, count=1)

    async def serve_static(
        self,
        pathname: str,
        request: Dict[str, Any],
        response: HttpResponseWriter,
        web_server: WebServerService,
        connection: Any,
    ) -> None:
        """Serve one GET/HEAD static request from the dist root."""
        target = url_join(self.dist_root, pathname)
        # Traversal rejection: the target must be the dist root itself (`/`) or
        # stay under it. `sep`, not '/', because a resolved path uses the
        # platform separator.
        if target != self.dist_root and not target.startswith(self.dist_root + os.sep):
            response.write_status(403)
            await response.finish()
            return
        try:
            if target == self.dist_root or target == self.dist_index:
                if not connection.authorize_index(request, response):
                    # The authorization owns this response and upstream ends it
                    # inside the call (node's res.end writes immediately); the
                    # port's writer buffers, so the caller flushes what the
                    # authorization wrote before returning.
                    await response.finish()
                    return
                body: Any = await self.render_index(web_server)
                content_type = HTML_MIME
            else:
                # A directory target is the EISDIR arm: Python exposes it as
                # IsADirectoryError on POSIX and PermissionError on Windows.
                if os.path.isdir(target):
                    raise IsADirectoryError(target)
                with open(target, "rb") as handle:
                    body = handle.read()
                _, extension = os.path.splitext(target)
                content_type = MIME_TYPES.get(extension, "application/octet-stream")
        except STATIC_MISS_ERRORS:
            # Only absent or non-file targets are 404; other filesystem failures
            # reach the webserver's request-failure handling.
            response.write_status(404)
            await response.finish()
            return
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        response.write_status(200)
        response.write_header("content-type", content_type)
        if request.get("method") == "HEAD":
            # node suppresses the body of a HEAD response but keeps its length.
            response.write_header("Content-Length", str(len(payload)))
        else:
            response.write_body(payload)
        await response.finish()

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server")
        if not web_server:
            return
        connection = ctx.get("connection")
        plugin = self

        async def handler(request: Dict[str, Any], response: HttpResponseWriter) -> None:
            # Non-GET/HEAD without a matching named route is 405 (fallback-only
            # semantics: named routes own their method handling).
            method = request.get("method", "GET")
            if method not in ("GET", "HEAD"):
                response.write_status(405)
                await response.finish()
                return
            pathname = decode_pathname(request.get("path") or "/")
            await plugin.serve_static(pathname, request, response, web_server, connection)

        disposer = web_server.register_fallback(handler)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)


def url_join(dist_root: str, pathname: str) -> str:
    """
    node:path `resolve(normalize(join(distRoot, pathname)))` over a URL pathname.

    `path.join` treats a leading '/' in its later arguments as relative, and on
    Windows it also treats '\\' as a separator: both matter because the servable
    path is decided before any filesystem call, and only a target that stays
    under the dist root may be served.
    """
    segments = [segment for segment in pathname.replace("\\", "/").split("/") if segment not in ("", ".")]
    if not segments:
        return os.path.normpath(dist_root)
    return os.path.normpath(os.path.join(dist_root, *segments))


def decode_pathname(raw_path: str) -> str:
    """
    `decodeURIComponent` over the raw pathname: percent escapes are decoded and
    a malformed escape or non-UTF-8 byte sequence raises, exactly the failure the
    node runtime propagates into the webserver's 400 guard.
    """
    from urllib.parse import unquote_to_bytes

    index = 0
    while True:
        index = raw_path.find("%", index)
        if index == -1:
            break
        escape = raw_path[index + 1:index + 3]
        if len(escape) < 2 or not all(c in "0123456789abcdefABCDEF" for c in escape):
            raise ValueError("frontend-static: malformed percent-encoding in request path")
        index += 3
    return unquote_to_bytes(raw_path).decode("utf-8", errors="strict")
