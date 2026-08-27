"""
Browser HTTP carrier service (`@deepseek-ai/dsh-host-webserver`).
Provides `ctx.web_server`, route registries (exact & prefix), index transform taps,
and fallback handler seat for SPA static serving.
"""

import asyncio
import http
import os
import socket
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dsh.cordis.plugin import Plugin
from dsh.host.webserver.injections import render_index_injections


class WebRoute:
    """Named route registration."""

    def __init__(
        self,
        kind: str,  # 'exact' or 'prefix'
        path: str,
        handler: Callable[[Any, Any], Coroutine[Any, Any, None]],
    ):
        self.kind = kind
        self.path = path.rstrip("/") if path != "/" else "/"
        self.handler = handler


class WebServerService:
    """
    WebServer Service mounted at `ctx.web_server` or `ctx.webServer`.
    """

    def __init__(self, ctx: Any, host: str = "127.0.0.1", port: int = 8080):
        self.ctx = ctx
        self.host = host
        self.port = port
        self.listened_port = port
        self._exact_routes: Dict[str, WebRoute] = {}
        self._prefix_routes: Dict[str, WebRoute] = {}
        self._upgrade_routes: Dict[str, Any] = {}
        self._fallback: Optional[Callable[[Any, Any], Coroutine[Any, Any, None]]] = None
        self._index_taps: List[Callable[[str], str]] = []
        self._server: Optional[asyncio.AbstractServer] = None
        self._is_running = False

    def register(self, kind: str, path: str, handler: Callable[[Any, Any], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        """Register a named route."""
        norm_path = path.rstrip("/") if path != "/" else "/"
        route = WebRoute(kind=kind, path=norm_path, handler=handler)
        table = self._exact_routes if kind == "exact" else self._prefix_routes
        table[norm_path] = route

        def disposer():
            table.pop(norm_path, None)

        return disposer

    def register_upgrade(self, path: str, handler: Any) -> Callable[[], None]:
        """Register an exact-path HTTP upgrade route (e.g. WebSocket)."""
        norm_path = path.rstrip("/") if path != "/" else "/"
        self._upgrade_routes[norm_path] = handler

        def disposer():
            self._upgrade_routes.pop(norm_path, None)

        return disposer

    def register_fallback(self, handler: Callable[[Any, Any], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        """Register the single fallback handler (e.g. SPA dist server)."""
        self._fallback = handler

        def disposer():
            if self._fallback == handler:
                self._fallback = None

        return disposer

    def tap_index(self, transform: Callable[[str], str]) -> Callable[[], None]:
        """Register an index.html transformation tap."""
        self._index_taps.append(transform)

        def disposer():
            if transform in self._index_taps:
                self._index_taps.remove(transform)

        return disposer

    def apply_index_taps(self, html: str) -> str:
        out = html
        for t in self._index_taps:
            out = t(out)
        return out

    def collect_index_injections(self) -> List[Dict[str, Any]]:
        """Gather structured injection table via `webserver/index-inject` event."""
        table: List[Dict[str, Any]] = []
        if hasattr(self.ctx, "emit"):
            self.ctx.emit("webserver/index-inject", table)
        return table

    def render_index(self, html: str) -> str:
        """Render index.html: structured injections first, then tap_index transforms."""
        injected = render_index_injections(html, self.collect_index_injections())
        return self.apply_index_taps(injected)

    def match(self, pathname: str) -> Optional[WebRoute]:
        norm = pathname.rstrip("/") if pathname != "/" else "/"
        if norm in self._exact_routes:
            return self._exact_routes[norm]
        best: Optional[WebRoute] = None
        for prefix, route in self._prefix_routes.items():
            if norm == prefix or norm.startswith(prefix + "/"):
                if best is None or len(prefix) > len(best.path):
                    best = route
        return best

    async def start(self) -> None:
        """Start the async HTTP server."""
        if self._is_running:
            return

        async def _client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await self._handle_http_connection(reader, writer)

        # Bind to port (or find free port if 0)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
            sock.listen(128)
            sock.setblocking(False)
            self.listened_port = sock.getsockname()[1]
        except OSError:
            # Fallback to random available port
            sock.bind((self.host, 0))
            sock.listen(128)
            sock.setblocking(False)
            self.listened_port = sock.getsockname()[1]

        self._server = await asyncio.start_server(
            _client_connected_cb,
            sock=sock,
        )
        self._is_running = True

    async def stop(self) -> None:
        """Stop the async HTTP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._is_running = False

    async def _handle_http_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return

            request_line = line.decode("utf-8", errors="ignore").strip()
            parts = request_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, raw_url = parts[0], parts[1]
            headers: Dict[str, str] = {}
            while True:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n" or header_line == b"\n":
                    break
                h_str = header_line.decode("utf-8", errors="ignore").strip()
                if ":" in h_str:
                    k, v = h_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            parsed = urlparse(raw_url)
            pathname = parsed.path or "/"

            request = {
                "method": method.upper(),
                "path": pathname,
                "query": parsed.query,
                "headers": headers,
                "body": body,
                "reader": reader,
            }

            response = HttpResponseWriter(writer)

            route = self.match(pathname)
            if route is not None:
                await route.handler(request, response)
            elif self._fallback is not None:
                await self._fallback(request, response)
            else:
                response.write_status(404)
                response.write_header("Content-Type", "text/plain; charset=utf-8")
                response.write_body(b"404 Not Found")
                await response.finish()

        except Exception as e:
            try:
                err_resp = HttpResponseWriter(writer)
                err_resp.write_status(500)
                err_resp.write_header("Content-Type", "text/plain; charset=utf-8")
                err_resp.write_body(f"500 Internal Server Error: {str(e)}".encode("utf-8"))
                await err_resp.finish()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass


class HttpResponseWriter:
    """Helper response writer for asyncio stream."""

    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.status = 200
        self.headers: Dict[str, str] = {}
        self.body = bytearray()
        self._headers_sent = False

    def write_status(self, status: int) -> None:
        self.status = status

    def write_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def write_body(self, data: bytes) -> None:
        self.body.extend(data)

    async def send_headers(self) -> None:
        if self._headers_sent:
            return
        status_phrase = http.HTTPStatus(self.status).phrase if self.status in http.HTTPStatus.__members__.values() else "OK"
        lines = [f"HTTP/1.1 {self.status} {status_phrase}"]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("\r\n")
        header_bytes = "\r\n".join(lines).encode("utf-8")
        self.writer.write(header_bytes)
        await self.writer.drain()
        self._headers_sent = True

    async def write_chunk(self, chunk: bytes) -> None:
        """Write chunk directly to open connection (e.g. SSE)."""
        if not self._headers_sent:
            await self.send_headers()
        self.writer.write(chunk)
        await self.writer.drain()

    async def finish(self) -> None:
        if not self._headers_sent:
            if "Content-Length" not in self.headers and "Transfer-Encoding" not in self.headers:
                self.headers["Content-Length"] = str(len(self.body))
            await self.send_headers()
        if self.body:
            self.writer.write(self.body)
            await self.writer.drain()


class WebServerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-webserver`: HTTP carrier for Web GUI and API proxy.
    """

    id = "webserver"
    name = "@deepseek-ai/dsh-host-webserver"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.host = (config or {}).get("host", "127.0.0.1")
        self.port = (config or {}).get("port", 8080)
        self.server_svc: Optional[WebServerService] = None

    def apply(self, ctx: Any) -> None:
        if ctx.get("web_server") is not None:
            return
        self.server_svc = WebServerService(ctx, host=self.host, port=self.port)
        ctx.set_service("web_server", self.server_svc)
        ctx.set_service("webServer", self.server_svc)

        async def _init_server():
            await self.server_svc.start()

        if hasattr(ctx, "effect"):
            ctx.effect(lambda: lambda: asyncio.create_task(self.server_svc.stop()))
