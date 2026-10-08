"""Owned urllib stream reads with idle timeout and active socket cancellation."""
import contextlib
import copy
import http.client
import io
import ipaddress
import math
import errno
import queue
import select
import socket
import ssl
import threading
import time
import urllib.request
import urllib.error
import urllib.parse

from dsh.core.cancellation import aborted


class _FetchRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, request, response, code, message, headers):
        location = headers.get('location')
        if location is None:
            return None
        try:
            target = urllib.parse.urljoin(request.full_url, location.replace(' ', '%20'))
            destination = urllib.parse.urlsplit(target)
            source = urllib.parse.urlsplit(request.full_url)
            if destination.scheme not in ('http', 'https'):
                raise ValueError('redirect target protocol is unsupported')
            if destination.username or destination.password:
                raise ValueError('redirect target credentials are unsupported')
            source_origin = (source.scheme, source.hostname, source.port or (443 if source.scheme == 'https' else 80))
            destination_origin = (destination.scheme, destination.hostname,
                                  destination.port or (443 if destination.scheme == 'https' else 80))
            count = getattr(request, '_dsh_redirect_count', 0)
            if count >= 20:
                raise ValueError('redirect count exceeded')
            method = request.get_method()
            rewrite = (code in (301, 302) and method == 'POST') or (code == 303 and method not in ('GET', 'HEAD'))
            excluded = {'host', 'content-length'}
            if rewrite:
                excluded.update(('content-type', 'content-encoding', 'content-language', 'content-location'))
            if source_origin != destination_origin:
                excluded.update(('authorization', 'proxy-authorization', 'cookie'))
            forwarded = {name: value for name, value in request.header_items() if name.lower() not in excluded}
            redirected = urllib.request.Request(target, data=None if rewrite else request.data, headers=forwarded,
                                                origin_req_host=request.origin_req_host, unverifiable=True,
                                                method='GET' if rewrite else method)
            redirected._dsh_redirect_count = count + 1
        except ValueError as error:
            response.close()
            raise urllib.error.URLError(str(error)) from error
        response.close()
        return self.parent.open(redirected, timeout=request.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, request, response, code, message, headers):
        response.close()
        raise urllib.error.URLError('HTTP redirect disallowed')

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


@contextlib.contextmanager
def open_stream(request, signal=None, idle_timeout_ms=300000, on_activity=None, read_error_body=True,
                redirect_policy='follow', raise_http_errors=True):
    from dsh.llm.llm_service import LlmError
    if redirect_policy not in ('follow', 'error'):
        raise ValueError('HTTP redirect policy must be follow or error')
    request = urllib.request.Request(request) if isinstance(request, str) else copy.copy(request)
    request.headers = {name: value for name, value in request.headers.items() if name.lower() != 'host'}
    request.unredirected_hdrs = {name: value for name, value in request.unredirected_hdrs.items() if name.lower() != 'host'}
    if type(idle_timeout_ms) not in (int, float) or not math.isfinite(idle_timeout_ms) or not 0 < idle_timeout_ms <= 2147483647:
        raise ValueError("streamIdleTimeoutMs must be a positive bounded timer")
    state = {"reading": False, "since": time.monotonic(), "code": None, "response": None}
    connections, stopped = [], threading.Event()

    def check():
        code = "ABORTED" if aborted(signal) else state["code"]
        if code:
            raise LlmError("Model request aborted" if code == "ABORTED" else "Model stream idle timeout", code)

    def wait_socket(sock, write=False):
        while True:
            check()
            ready = select.select([] if write else [sock], [sock] if write else [], [], 0.02)
            if ready[1 if write else 0]:
                return

    def connect_socket(address, timeout=None, source_address=None):
        try:
            numeric = str(ipaddress.IPv4Address(address[0]))
        except ipaddress.AddressValueError:
            numeric = None
        if numeric is not None:
            addresses = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                          '', (numeric, address[1]))]
        else:
            # getaddrinfo has no cancellable API on Python 3.8/Win7. Bound
            # hostname waits; an abandoned DNS worker owns no sockets.
            resolved = queue.Queue(maxsize=1)
            def resolve():
                try:
                    resolved.put(socket.getaddrinfo(address[0], address[1], 0, socket.SOCK_STREAM))
                except Exception as error:
                    resolved.put(error)
            resolver = threading.Thread(target=resolve, name="dsh-http-dns", daemon=True)
            resolver.start()
            while True:
                check()
                try:
                    addresses = resolved.get(timeout=0.02)
                    break
                except queue.Empty:
                    pass
        if isinstance(addresses, Exception):
            raise addresses
        last_error = None
        for family, kind, protocol, _, target in addresses:
            check()
            sock = socket.socket(family, kind, protocol)
            try:
                sock.setblocking(False)
                if source_address:
                    sock.bind(source_address)
                result = sock.connect_ex(target)
                if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037):
                    raise OSError(result, "connection failed")
                if result:
                    wait_socket(sock, write=True)
                    failure = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if failure:
                        raise OSError(failure, "connection failed")
                return sock
            except BaseException as error:
                sock.close()
                if not isinstance(error, OSError):
                    raise
                last_error = error
        raise last_error or OSError("DNS returned no connection addresses")

    def factory(connection_type):
        class CheckedRaw(io.RawIOBase):
            def __init__(self, sock):
                self._sock = sock
                self.source = sock.makefile("rb", buffering=0)

            def close(self):
                self.source.close()
                super().close()

            def readable(self):
                return True

            def readinto(self, buffer):
                while True:
                    check()
                    try:
                        count = self._sock.recv_into(buffer)
                        if count:
                            state["since"] = time.monotonic()
                            if on_activity is not None:
                                on_activity()
                        return count
                    except (BlockingIOError, ssl.SSLWantReadError):
                        wait_socket(self._sock)
                    except ssl.SSLWantWriteError:
                        wait_socket(self._sock, write=True)

        class SocketView:
            def __init__(self, sock):
                self.sock = sock

            def makefile(self, *_args, **_kwargs):
                return io.BufferedReader(CheckedRaw(self.sock))

        class CheckedResponse(http.client.HTTPResponse):
            def __init__(self, sock, *args, **kwargs):
                super().__init__(SocketView(sock), *args, **kwargs)

        class OwnedConnection(connection_type):
            response_class = CheckedResponse

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = connect_socket

            def connect(self):
                http.client.HTTPConnection.connect(self)
                if connection_type is http.client.HTTPSConnection:
                    hostname = self._tunnel_host or self.host
                    self.sock = self._context.wrap_socket(self.sock, server_hostname=hostname,
                                                          do_handshake_on_connect=False)
                    while True:
                        check()
                        try:
                            self.sock.do_handshake()
                            break
                        except ssl.SSLWantReadError:
                            wait_socket(self.sock)
                        except ssl.SSLWantWriteError:
                            wait_socket(self.sock, write=True)

            def send(self, data):
                if self.sock is None:
                    self.connect()
                if hasattr(data, "read"):
                    while True:
                        chunk = data.read(self.blocksize)
                        if not chunk:
                            return
                        self.send(chunk.encode("iso-8859-1") if isinstance(chunk, str) else chunk)
                else:
                    pending = memoryview(data)
                    while pending:
                        check()
                        try:
                            sent = self.sock.send(pending)
                            if not sent:
                                raise OSError("connection closed during request write")
                            pending = pending[sent:]
                            state["since"] = time.monotonic()
                            if on_activity is not None:
                                on_activity()
                        except (BlockingIOError, ssl.SSLWantWriteError):
                            wait_socket(self.sock, write=True)
                        except ssl.SSLWantReadError:
                            wait_socket(self.sock)
        def create(*args, **kwargs):
            connection = OwnedConnection(*args, **kwargs)
            connections.append(connection)
            return connection
        return create

    class Http(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(factory(http.client.HTTPConnection), req)

    class Https(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(factory(http.client.HTTPSConnection), req,
                                context=self._context, check_hostname=self._check_hostname)

    def shutdown_socket():
        sockets = [connection.sock for connection in connections if connection.sock is not None]
        response = state["response"]
        # urllib detaches HTTPConnection.sock for Connection: close responses;
        # HTTPResponse's buffered file retains that same transport socket.
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sockets.append(sock)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def watch():
        while not stopped.wait(0.01):
            if aborted(signal):
                state["code"] = "ABORTED"
            elif state["reading"] and time.monotonic() - state["since"] >= idle_timeout_ms / 1000:
                state["code"] = "TIMEOUT"

    def read_chunks(response):
        while True:
            check()
            state.update(reading=True, since=time.monotonic())
            try:
                chunk = response.read1(65536)
            except socket.timeout:
                state["code"] = "TIMEOUT"
                check()
            except http.client.HTTPException as error:
                check()
                # Broken HTTP framing (including truncated chunked bodies) is
                # a transport failure, not an unclassified model exception.
                # Never turn a partial response into a completed summary.
                raise LlmError("Model HTTP stream interrupted: {}".format(error), "TRANSPORT") from error
            except (OSError, ValueError):
                check()
                raise
            finally:
                state["reading"] = False
            check()
            if not chunk:
                return
            yield chunk

    check()
    watcher = threading.Thread(target=watch, name="dsh-http-cancellation", daemon=True)
    watcher.start()
    response = None
    try:
        state.update(reading=True, since=time.monotonic())
        try:
            redirect = _FetchRedirectHandler() if redirect_policy == 'follow' else _RejectRedirectHandler()
            response = urllib.request.build_opener(Http(), Https(), redirect).open(request, timeout=idle_timeout_ms / 1000)
        except urllib.error.HTTPError as error:
            response = state["response"] = error
            if raise_http_errors:
                error._dsh_body = b"".join(read_chunks(error)) if read_error_body else b""
                raise
        except urllib.error.URLError as error:
            if isinstance(error.reason, socket.timeout):
                state["code"] = "TIMEOUT"
            check()
            raise
        except socket.timeout as error:
            state["code"] = "TIMEOUT"
            check()
            raise error
        except Exception:
            check()
            raise
        finally:
            state["reading"] = False
        state["response"] = response
        check()
        yield response, read_chunks(response)
    finally:
        stopped.set()
        shutdown_socket()
        if response is not None:
            response.close()
        for connection in connections:
            connection.close()
        watcher.join(timeout=1)
