"""
SPA dist server over the webserver fallback seat (`@deepseek-ai/dsh-host-frontend-static`).
Serves built frontend directory with SPA routing (miss falls back to index.html with HTTP 200).
"""

import mimetypes
import os
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

MIME_TYPES: Dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}


class FrontendStaticPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-frontend-static`: Serves static web frontend SPA.
    """

    id = "frontend-static"
    name = "@deepseek-ai/dsh-host-frontend-static"
    inject = ["web_server"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        candidates = [
            os.path.join(repo_root, "reference", "deepseek-harness", "apps", "web", "dist", "index.html"),
            os.path.join(repo_root, "apps", "web", "dist", "index.html"),
            os.path.join(repo_root, "apps", "web", "index.html"),
        ]
        chosen = cfg.get("distIndex")
        if not chosen:
            for c in candidates:
                if os.path.isfile(c):
                    chosen = c
                    break
        self.dist_index = chosen or candidates[-1]
        self.dist_root = os.path.dirname(self.dist_index)

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server")
        if not web_server:
            return

        async def serve_static(request: Dict[str, Any], response: HttpResponseWriter) -> None:
            method = request.get("method", "GET")
            if method not in ("GET", "HEAD"):
                response.write_status(405)
                response.write_header("Content-Type", "text/plain; charset=utf-8")
                response.write_body(b"405 Method Not Allowed")
                await response.finish()
                return

            raw_path = request.get("path", "/").lstrip("/")
            target = os.path.normpath(os.path.join(self.dist_root, raw_path))

            # Security check: must not escape dist_root
            if not target.startswith(self.dist_root):
                response.write_status(403)
                response.write_header("Content-Type", "text/plain; charset=utf-8")
                response.write_body(b"403 Forbidden")
                await response.finish()
                return

            async def _send_index() -> None:
                if os.path.exists(self.dist_index):
                    with open(self.dist_index, "r", encoding="utf-8") as f:
                        content = f.read()
                    transformed = web_server.apply_index_taps(content)
                    body = transformed.encode("utf-8")
                    response.write_status(200)
                    response.write_header("Content-Type", MIME_TYPES[".html"])
                    response.write_body(body)
                    await response.finish()
                else:
                    response.write_status(404)
                    response.write_header("Content-Type", "text/plain; charset=utf-8")
                    response.write_body(b"404 Frontend index.html Not Found")
                    await response.finish()

            if target == self.dist_root or target == self.dist_index:
                await _send_index()
                return

            if os.path.isfile(target):
                _, ext = os.path.splitext(target)
                mime = MIME_TYPES.get(ext.lower(), mimetypes.guess_type(target)[0] or "application/octet-stream")
                try:
                    with open(target, "rb") as f:
                        data = f.read()
                    response.write_status(200)
                    response.write_header("Content-Type", mime)
                    response.write_body(data)
                    await response.finish()
                    return
                except Exception:
                    await _send_index()
                    return

            # Miss: fallback to index.html with HTTP 200 (SPA routing)
            await _send_index()

        disposer = web_server.register_fallback(serve_static)
        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)
