"""
Browser HTTP carrier service (`@deepseek-ai/dsh-host-webserver`).
Provides `ctx.web_server`, route registries (exact & prefix), exact-path upgrade
routes with request-level 101 dispatch, index transform taps, optional gzip
response compression (`compression`/`compressionLevel`/`compressionThresholdBytes`,
the reference defaults, and the reference eligibility rules), and the fallback
handler seat for SPA static serving.

Registration is a composition-level contract: duplicate named routes, duplicate
upgrade routes and a second fallback seat all fail loudly (reference
`webserver: duplicate ...` / `webserver: fallback already registered`). An
unclaimed fallback answers 404 with an empty body, and a request whose handling
raises is logged and answered 400 — never a process exit.
"""

import asyncio
import http
import os
import socket
import zlib
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dsh.cordis.plugin import Plugin
from dsh.host.webserver.injections import render_index_injections
from dsh.host.webserver.socket_server import OwnedSocketServer


DEFAULT_COMPRESSION = "none"
DEFAULT_COMPRESSION_LEVEL = 1
DEFAULT_COMPRESSION_THRESHOLD_BYTES = 1024
COMPRESSION_MODES = ("none", "gzip")

# The DEFLATE window bits selecting the gzip container in `zlib` (`15 + 16`),
# the Python equivalent of node:zlib's `createGzip`.
GZIP_WINDOW_BITS = 31

# `compressible`'s verdicts for the media types this carrier serves: the text,
# JSON and XML families plus SVG compress; archive, media and font payloads are
# already compressed and must not be re-encoded.
COMPRESSIBLE_TYPES = frozenset((
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/manifest+json",
    "application/x-www-form-urlencoded",
    "application/vnd.ms-fontobject",
    "image/svg+xml",
))
NOT_COMPRESSIBLE_TYPES = frozenset((
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/x-bzip2",
    "application/pdf",
))


def resolve_web_server_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Validate and default one webserver config exactly like the reference
    `WebServer.Config` (host/port literals, `compression` in `none|gzip`,
    `compressionLevel` an integer step 1 from 0 through 9,
    `compressionThresholdBytes` a natural number).
    """
    cfg = dict(config or {})
    host = cfg.get("host", "127.0.0.1")
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("webserver: host must be '127.0.0.1' or '0.0.0.0'")
    port = cfg.get("port", 0)
    if not isinstance(port, int) or isinstance(port, bool) or port < 0 or port > 65535:
        raise ValueError("webserver: port must be a natural number no greater than 65535")
    compression = cfg.get("compression", DEFAULT_COMPRESSION)
    if compression not in COMPRESSION_MODES:
        raise ValueError("webserver: compression must be 'none' or 'gzip'")
    level = cfg.get("compressionLevel", DEFAULT_COMPRESSION_LEVEL)
    if not isinstance(level, int) or isinstance(level, bool) or level < 0 or level > 9:
        raise ValueError("webserver: compressionLevel must be an integer from 0 through 9")
    threshold = cfg.get("compressionThresholdBytes", DEFAULT_COMPRESSION_THRESHOLD_BYTES)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 0:
        raise ValueError("webserver: compressionThresholdBytes must be a natural number")
    return {
        "host": host,
        "port": port,
        "compression": compression,
        "compressionLevel": level,
        "compressionThresholdBytes": threshold,
    }


def is_compressible(content_type: Any) -> bool:
    """`compression`'s `compressible(content-type)` filter verdict."""
    if not isinstance(content_type, str):
        return False
    mime = content_type.split(";")[0].strip().lower()
    if not mime or mime in NOT_COMPRESSIBLE_TYPES:
        return False
    if mime.startswith("text/"):
        return True
    if mime.endswith("+json") or mime.endswith("+xml"):
        return True
    return mime in COMPRESSIBLE_TYPES


def parse_accept_encoding(value: Any) -> List[Tuple[str, float, int]]:
    """
    One `accept-encoding` header as `(encoding, quality, position)` specs.

    `identity` is implicitly acceptable unless the header names it, scoring the
    lowest quality the header states -- the negotiator contract the reference's
    `encoding(['gzip', 'identity'])` call relies on.
    """
    specs: List[Tuple[str, float, int]] = []
    has_identity = False
    min_quality = 1.0
    if isinstance(value, str):
        for position, entry in enumerate(value.split(",")):
            parts = entry.split(";")
            name = parts[0].strip().lower()
            if not name:
                continue
            quality = 1.0
            for param in parts[1:]:
                key, _, raw = param.partition("=")
                if key.strip().lower() != "q":
                    continue
                try:
                    quality = float(raw.strip())
                except ValueError:
                    quality = 0.0
                if quality != quality:  # NaN is not a quality
                    quality = 0.0
            specs.append((name, quality, position))
            if name == "identity":
                has_identity = True
            min_quality = min(min_quality, quality if quality > 0 else 1.0)
    if not has_identity:
        specs.append(("identity", min_quality, len(specs)))
    return specs


def negotiate_encoding(accept_encoding: Any, available: List[str]) -> Optional[str]:
    """
    The most preferred acceptable encoding, or `None` when none is acceptable.

    An absent or empty header yields `identity`: the negotiator parse finds no
    acceptable token at all, so only the implicit `identity` entry matches.
    """
    specs = [spec for spec in parse_accept_encoding(accept_encoding) if spec[1] > 0]
    specs.sort(key=lambda spec: (-spec[1], spec[2]))
    for name, _quality, _position in specs:
        if name == "*":
            return available[0] if available else None
        if name in available:
            return name
    return None


class ResponseCompression:
    """
    One response's gzip decision, the port of `createGzipMiddleware`.

    Upstream negotiates `gzip`/`identity` from the request, overrides the
    request's `accept-encoding` with the winner, and hands the response to the
    `compression` middleware whose eligibility rule is: no `content-range`,
    never `text/event-stream`, and a compressible content type.
    """

    def __init__(self, level: int, threshold_bytes: int, accept_encoding: Any):
        self.level = level
        self.threshold_bytes = threshold_bytes
        self.encoding = negotiate_encoding(accept_encoding, ["gzip", "identity"])

    def filter_passes(self, content_range: Optional[str], content_type: Optional[str]) -> bool:
        """The middleware's filter: is this response even considered?"""
        if content_range is not None:
            return False
        if isinstance(content_type, str) and content_type.lower().startswith("text/event-stream"):
            return False
        return is_compressible(content_type)

    def encodes(self, content_length: Optional[int]) -> bool:
        """Gzip this body? Unknown lengths are eligible; short known ones are not."""
        if self.encoding != "gzip":
            return False
        if content_length is not None and content_length < self.threshold_bytes:
            return False
        return True


def is_upgrade_request(headers: Dict[str, str]) -> bool:
    """node:http emits `upgrade` for a request carrying Upgrade and Connection: Upgrade."""
    if not headers.get("upgrade"):
        return False
    tokens = [token.strip().lower() for token in headers.get("connection", "").split(",")]
    return "upgrade" in tokens


class WebRoute:
    """
    Named route registration.

    `path` is used verbatim: the reference treats it as an absolute pathname
    without a trailing slash (a caller contract) and never rewrites it, so a
    registration at `/probe/` and a request for `/probe` are different keys.
    """

    def __init__(
        self,
        kind: str,  # 'exact' or 'prefix'
        path: str,
        handler: Callable[[Any, Any], Coroutine[Any, Any, None]],
    ):
        self.kind = kind
        self.path = path
        self.handler = handler


class WebServerService:
    """
    WebServer Service mounted at `ctx.web_server` or `ctx.webServer`.
    """

    def __init__(
        self,
        ctx: Any,
        host: str = "127.0.0.1",
        port: int = 8080,
        compression: str = DEFAULT_COMPRESSION,
        compression_level: int = DEFAULT_COMPRESSION_LEVEL,
        compression_threshold_bytes: int = DEFAULT_COMPRESSION_THRESHOLD_BYTES,
    ):
        self.ctx = ctx
        self.host = host
        self.port = port
        self.listened_port = port
        self.compression = compression
        self.compression_level = compression_level
        self.compression_threshold_bytes = compression_threshold_bytes
        self._exact_routes: Dict[str, WebRoute] = {}
        self._prefix_routes: Dict[str, WebRoute] = {}
        self._upgrade_routes: Dict[str, Any] = {}
        self._fallback: Optional[Callable[[Any, Any], Coroutine[Any, Any, None]]] = None
        self._index_taps: List[Callable[[str], str]] = []
        self._server: Optional[asyncio.AbstractServer] = None
        self._is_running = False
        # Sockets handed to an upgrade handler: node leaves upgraded sockets out
        # of `closeAllConnections()`, so the service owns them explicitly.
        self._upgraded_sockets: List[asyncio.StreamWriter] = []
        self._connections: Dict[Any, Any] = {}

    @staticmethod
    def resolve_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """The reference `WebServer.Config`: validate and default one config."""
        return resolve_web_server_config(config)

    def register(self, kind: str, path: str, handler: Callable[[Any, Any], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        """
        Register a named route. Duplicate (kind, path) raises — route patterns
        are a composition-level contract, so a collision is a misconfiguration.
        """
        table = self._exact_routes if kind == "exact" else self._prefix_routes
        if path in table:
            raise ValueError(f'webserver: duplicate {kind} route "{path}"')
        route = WebRoute(kind=kind, path=path, handler=handler)
        table[path] = route

        def disposer():
            table.pop(path, None)

        return disposer

    def register_upgrade(self, path: str, handler: Any) -> Callable[[], None]:
        """
        Register an exact-path HTTP upgrade route (e.g. WebSocket). Duplicate
        paths raise because one socket can have only one protocol owner.
        """
        if path in self._upgrade_routes:
            raise ValueError(f'webserver: duplicate upgrade route "{path}"')
        self._upgrade_routes[path] = handler

        def disposer():
            self._upgrade_routes.pop(path, None)

        return disposer

    def register_fallback(self, handler: Callable[[Any, Any], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        """
        Claim the fallback seat: the handler answering every request no named
        route matches. One owner only — a second registration raises, because
        two fallbacks cannot compose.
        """
        if self._fallback is not None:
            raise ValueError("webserver: fallback already registered")
        self._fallback = handler

        def disposer():
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
        rendered = self.apply_index_taps(injected)
        compatibility = self.ctx.get('browserCompatibility') if hasattr(self.ctx, 'get') else None
        return compatibility.validate_index(rendered) if compatibility is not None else rendered

    def _response_compression(self, headers: Dict[str, str]) -> Optional[ResponseCompression]:
        """
        The gzip middleware decision for one request, or None when the carrier
        was configured `compression: none` (upstream constructs no middleware).
        """
        if self.compression != "gzip":
            return None
        return ResponseCompression(
            self.compression_level,
            self.compression_threshold_bytes,
            headers.get("accept-encoding"),
        )

    def match(self, pathname: str) -> Optional[WebRoute]:
        """
        Longest-prefix-wins over the prefix table after an exact-table miss.

        Both lookups use the request pathname verbatim: `/probe/` is not a
        match for a route registered at `/probe`.
        """
        exact = self._exact_routes.get(pathname)
        if exact is not None:
            return exact
        best: Optional[WebRoute] = None
        for prefix, route in self._prefix_routes.items():
            if pathname != prefix and not pathname.startswith(prefix + "/"):
                continue
            if best is None or len(prefix) > len(best.path):
                best = route
        return best

    async def start(self) -> None:
        """Start the async HTTP server."""
        if self._is_running:
            return

        async def _client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self._connections[writer] = asyncio.current_task()
            try:
                await self._handle_http_connection(reader, writer)
            finally:
                self._connections.pop(writer, None)
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

        # Bind to port (or find free port if 0). A listen failure rejects
        # activation: the composition reports the failed fiber instead of
        # silently serving on a different port than the one configured.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # POSIX: reuse a socket in TIME_WAIT. On Windows SO_REUSEADDR means
            # "allow hijacking a bound port", which would silently let a second
            # composition claim a taken port instead of failing loud the way the
            # reference listen does (libuv sets no such option there).
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.host, self.port))
            sock.listen(128)
            sock.setblocking(False)
            self.listened_port = sock.getsockname()[1]
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            raise

        try:
            if os.name == "nt":
                self._server = OwnedSocketServer(sock, _client_connected_cb, self._log_warning)
            else:
                self._server = await asyncio.start_server(_client_connected_cb, sock=sock)
        except BaseException:
            sock.close()
            raise
        self.port = self.listened_port
        self._is_running = True

    async def stop(self) -> None:
        """Stop the async HTTP server and every socket it handed to an upgrade."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        connections = list(self._connections.items())
        for writer, task in connections:
            writer.close()
            if task is not asyncio.current_task():
                task.cancel()
        await asyncio.gather(*(task for _, task in connections if task is not asyncio.current_task()), return_exceptions=True)
        upgraded = list(self._upgraded_sockets)
        self._upgraded_sockets = []
        for writer in upgraded:
            try:
                writer.close()
            except Exception:
                pass
        for writer in upgraded:
            try:
                await writer.wait_closed()
            except Exception:
                pass
        self._is_running = False

    def _log_warning(self, error: Any) -> None:
        try:
            if self.ctx is not None and hasattr(self.ctx, "logger"):
                self.ctx.logger("webserver").warn(error)
        except Exception:
            pass

    @staticmethod
    def _destroy_socket(writer: asyncio.StreamWriter) -> None:
        """`socket.destroy()`: abort the transport, discarding buffered bytes."""
        transport = getattr(writer, "transport", None)
        if transport is not None:
            try:
                transport.abort()
                return
            except Exception:
                pass
        try:
            writer.close()
        except Exception:
            pass

    def _forget_upgraded(self, writer: asyncio.StreamWriter) -> None:
        try:
            self._upgraded_sockets.remove(writer)
        except ValueError:
            pass

    async def _watch_upgraded(self, writer: asyncio.StreamWriter) -> None:
        """Drop an upgraded socket from the tracked set when it closes."""
        try:
            await writer.wait_closed()
        except Exception:
            pass
        finally:
            self._forget_upgraded(writer)

    async def _dispatch_upgrade(self, request: Dict[str, Any], writer: asyncio.StreamWriter) -> None:
        """
        Route one raw upgrade request to its exact-path owner.

        The path is matched verbatim against the upgrade table. A path no route
        claims destroys the socket, exactly like the reference listener. A
        claimed socket is tracked so teardown closes it with the other
        connections, and every handler or transport failure is contained by
        destroying the socket -- never a process-level failure path.
        """
        handler = self._upgrade_routes.get(request.get("path") or "/")
        if handler is None:
            self._destroy_socket(writer)
            return
        self._upgraded_sockets.append(writer)
        asyncio.ensure_future(self._watch_upgraded(writer))
        try:
            result = handler(request, writer)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            self._log_warning(e)
            self._destroy_socket(writer)
            self._forget_upgraded(writer)

    async def _handle_http_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        response: Optional[HttpResponseWriter] = None
        upgraded = False
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
            parsed = urlparse(raw_url)
            pathname = parsed.path or "/"
            route = self.match(pathname)
            deferred = route is not None and getattr(route.handler, "defer_body", False)
            if content_length > 0 and not deferred:
                body = await reader.readexactly(content_length)

            parsed = urlparse(raw_url)
            pathname = parsed.path or "/"

            request = {
                "method": method.upper(),
                "path": pathname,
                "raw_url": raw_url,
                "query": parsed.query,
                "headers": headers,
                "body": body,
                "reader": reader,
                "body_deferred": deferred,
            }

            # A request-level upgrade is dispatched before any HTTP response
            # exists: the handler owns protocol negotiation and the socket from
            # its 101 onward, so this loop must not answer or close it.
            if is_upgrade_request(headers):
                upgraded = True
                await self._dispatch_upgrade(request, writer)
                return

            response = HttpResponseWriter(
                writer, compression=self._response_compression(headers)
            )

            route = self.match(pathname)
            if route is not None:
                await route.handler(request, response)
            elif self._fallback is not None:
                await self._fallback(request, response)
            else:
                # Unclaimed fallback seat: an empty 404, exactly like every other
                # unmatched request the composing application never handled.
                response.write_status(404)
                await response.finish()

        except Exception as e:
            # Last-resort guard: an unhandled per-request failure (a malformed
            # %-escape, a client dropping mid-body, a filesystem error that is
            # not a static miss) logs and answers 400 — never a process exit.
            try:
                if self.ctx is not None and hasattr(self.ctx, "logger"):
                    self.ctx.logger("webserver").warn(e)
            except Exception:
                pass
            try:
                if response is not None and response._headers_sent:
                    writer.close()
                else:
                    err_resp = HttpResponseWriter(writer)
                    err_resp.write_status(400)
                    await err_resp.finish()
            except Exception:
                pass
        finally:
            # An upgraded socket belongs to its handler and is tracked by the
            # service until teardown; only ordinary requests close here.
            if not upgraded:
                try:
                    writer.close()
                    # Await the real close: the response bytes are queued on the
                    # transport, and closing without waiting can drop a body-less
                    # response (headers only) on the proactor loop.
                    await writer.wait_closed()
                except Exception:
                    pass


class HttpResponseWriter:
    """
    Helper response writer for asyncio stream.

    `compression` carries one response's optional gzip decision (upstream's
    negotiated middleware); it is applied when the headers are first written,
    exactly where the node carrier decides at first write. SSE and range
    responses keep identity bytes.
    """

    def __init__(
        self,
        writer: asyncio.StreamWriter,
        compression: Optional[ResponseCompression] = None,
    ):
        self.writer = writer
        self.status = 200
        self.headers: Dict[str, str] = {}
        self.body = bytearray()
        self._headers_sent = False
        self.compression = compression
        self._compressing = False
        self._gzip_stream: Optional[Any] = None

    def write_status(self, status: int) -> None:
        self.status = status

    def write_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def write_body(self, data: bytes) -> None:
        self.body.extend(data)

    def header(self, name: str) -> Optional[str]:
        """Read one response header, case-insensitively like node's header table."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def _set_header(self, name: str, value: str) -> None:
        lowered = name.lower()
        for key in list(self.headers.keys()):
            if key.lower() == lowered:
                self.headers[key] = value
                return
        self.headers[name] = value

    def _drop_header(self, name: str) -> None:
        lowered = name.lower()
        for key in list(self.headers.keys()):
            if key.lower() == lowered:
                del self.headers[key]

    def _prepare_compression(self) -> None:
        """
        Apply the gzip decision at first write.

        The eligibility filter decides `Vary: Accept-Encoding` on its own, so an
        identity response (a lower-quality gzip, an unknown accept-encoding) is
        still marked as negotiated. Encoding happens only for a gzip request
        whose known length clears the threshold and whose response carries no
        encoding yet; the content-length is dropped because the body length is
        no longer the declared one.
        """
        compression = self.compression
        if compression is None or self._compressing:
            return
        if not compression.filter_passes(self.header("content-range"), self.header("content-type")):
            return
        vary = self.header("vary")
        if vary is None:
            self._set_header("Vary", "Accept-Encoding")
        elif "accept-encoding" not in vary.lower():
            self._set_header("Vary", vary + ", Accept-Encoding")
        if self.header("content-encoding") is not None:
            return
        length: Optional[int] = None
        raw_length = self.header("content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                length = None
        if not compression.encodes(length):
            return
        self._compressing = True
        self._drop_header("content-length")
        self._set_header("Content-Encoding", "gzip")
        self._gzip_stream = zlib.compressobj(compression.level, zlib.DEFLATED, GZIP_WINDOW_BITS)

    async def send_headers(self) -> None:
        if self._headers_sent:
            return
        self._drop_header("Connection")
        self._set_header("Connection", "close")
        self._prepare_compression()
        status_phrase = http.HTTPStatus(self.status).phrase if self.status in http.HTTPStatus.__members__.values() else "OK"
        lines = [f"HTTP/1.1 {self.status} {status_phrase}"]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("\r\n")
        header_bytes = "\r\n".join(lines).encode("utf-8")
        self.writer.write(header_bytes)
        await self.writer.drain()
        self._headers_sent = True

    async def _write_encoded(self, data: bytes) -> None:
        if self._compressing and self._gzip_stream is not None:
            data = self._gzip_stream.compress(data)
            if not data:
                return
        self.writer.write(data)
        await self.writer.drain()

    async def write_chunk(self, chunk: bytes) -> None:
        """Write chunk directly to open connection (e.g. SSE)."""
        if not self._headers_sent:
            await self.send_headers()
        await self._write_encoded(chunk)

    async def finish(self) -> None:
        if not self._headers_sent:
            self._prepare_compression()
            if (
                not self._compressing
                and self.header("Content-Length") is None
                and self.header("Transfer-Encoding") is None
            ):
                self._set_header("Content-Length", str(len(self.body)))
            await self.send_headers()
        if self.body:
            await self._write_encoded(bytes(self.body))
        if self._compressing and self._gzip_stream is not None:
            tail = self._gzip_stream.flush()
            if tail:
                self.writer.write(tail)
                await self.writer.drain()
            self._gzip_stream = None


class WebServerPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-webserver`: HTTP carrier for Web GUI and API proxy.
    """

    id = "webserver"
    name = "@deepseek-ai/dsh-host-webserver"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = dict(config or {})
        cfg.setdefault("host", "127.0.0.1")
        cfg.setdefault("port", 0)
        resolved = resolve_web_server_config(cfg)
        self.host = resolved["host"]
        self.port = resolved["port"]
        self.compression = resolved["compression"]
        self.compression_level = resolved["compressionLevel"]
        self.compression_threshold_bytes = resolved["compressionThresholdBytes"]
        self.server_svc: Optional[WebServerService] = None

    async def apply(self, ctx: Any) -> None:
        self.server_svc = WebServerService(
            ctx,
            host=self.host,
            port=self.port,
            compression=self.compression,
            compression_level=self.compression_level,
            compression_threshold_bytes=self.compression_threshold_bytes,
        )
        ctx.effect(lambda: self.server_svc.stop, "webServer.listen")
        await self.server_svc.start()
        ctx.set_service("web_server", self.server_svc)
        ctx.set_service("webServer", self.server_svc)
