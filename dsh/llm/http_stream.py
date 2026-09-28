"""Owned urllib stream reads with idle timeout and active socket cancellation."""
import contextlib
import http.client
import io
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

from dsh.core.cancellation import aborted


@contextlib.contextmanager
def open_stream(request, signal=None, idle_timeout_ms=300000):
    from dsh.llm.llm_service import LlmError
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
        # getaddrinfo has no cancellable API on Python 3.8/Win7. Bound the
        # caller's wait; an abandoned DNS worker owns no transport sockets.
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
            response = urllib.request.build_opener(Http(), Https()).open(request, timeout=idle_timeout_ms / 1000)
        except urllib.error.HTTPError as error:
            response = state["response"] = error
            error._dsh_body = b"".join(read_chunks(error))
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
