"""Owned urllib stream reads with idle timeout and active socket cancellation."""
import contextlib
import http.client
import io
import math
import select
import socket
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
                    if callable(getattr(self._sock, "pending", None)) and self._sock.pending():
                        break
                    if select.select([self._sock], [], [], 0.02)[0]:
                        break
                check()
                return self.source.readinto(buffer)

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

            def connect(self):
                super().connect()
                self.sock.settimeout(None)
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
