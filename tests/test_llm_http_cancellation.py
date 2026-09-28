import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.llm.llm_service import LLMService, LlmError


@pytest.fixture
def server():
    state = {"mode": "body", "entered": threading.Event(), "release": threading.Event()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["entered"].set()
            if state["mode"] == "headers":
                state["release"].wait(2)
                return
            if state["mode"] == "retry":
                body = b'{"error":{"message":"quota"}}'
                self.send_response(429)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Retry-After", "2")
                self.send_header("x-request-id", "request-test")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if state["mode"] == "progress":
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
            self.wfile.flush()
            state["release"].wait(2)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield LLMService(api_key="local-only", base_url="http://127.0.0.1:{}".format(http.server_port)), state
    finally:
        state["release"].set()
        http.shutdown()
        http.server_close()
        worker.join(1)


@pytest.mark.parametrize("mode", ["headers", "body"])
def test_stalled_http_times_out_with_typed_failure(server, mode):
    llm, state = server
    state["mode"] = mode
    start = time.monotonic()
    with pytest.raises(LlmError) as caught:
        list(llm.chat_completion_stream([], model="test", streamIdleTimeoutMs=80))
    assert caught.value.code == "TIMEOUT"
    assert time.monotonic() - start < 1
    assert not any(t.name == "dsh-http-cancellation" for t in threading.enumerate())


@pytest.mark.parametrize("mode", ["headers", "body"])
def test_cancel_interrupts_actual_http_reader_and_drains_watchdog(server, mode):
    llm, state = server
    state["mode"] = mode
    cancel, failures = threading.Event(), []
    def consume():
        try:
            list(llm.chat_completion_stream([], model="test", signal=cancel, streamIdleTimeoutMs=10000))
        except LlmError as error:
            failures.append(error.code)
    worker = threading.Thread(target=consume, daemon=True)
    worker.start()
    try:
        assert state["entered"].wait(1)
        cancel.set()
        worker.join(1)
        assert not worker.is_alive()
        assert failures == ["ABORTED"]
        assert not any(t.name == "dsh-http-cancellation" for t in threading.enumerate())
    finally:
        cancel.set()
        state["release"].set()
        worker.join(1)


def test_provider_retry_after_request_id_and_error_body_survive_transport_cleanup(server):
    llm, state = server
    state["mode"] = "retry"
    with pytest.raises(LlmError) as caught:
        list(llm.chat_completion_stream([], model="test"))
    assert caught.value.code == "RATE_LIMIT"
    assert caught.value.providerRetryAfterMs == 2000
    assert caught.value.requestId == "request-test"
    assert "quota" in str(caught.value)


@pytest.mark.parametrize("stage", ["handshake", "partial-record"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_tls_stalls_are_bounded_in_handshake_and_partial_record(monkeypatch, stage, cancelled):
    import socket
    import ssl
    from pathlib import Path
    root = Path(__file__).parent / "fixtures" / "tls"
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(root / "localhost-cert.pem"), str(root / "localhost-key.pem"))
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda: ssl.create_default_context(cafile=str(root / "localhost-cert.pem")))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    entered, release, signal = threading.Event(), threading.Event(), threading.Event()
    def serve():
        connection, _ = listener.accept()
        try:
            if stage == "partial-record":
                incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
                channel = server_context.wrap_bio(incoming, outgoing, server_side=True)
                while True:
                    try:
                        channel.do_handshake()
                        if outgoing.pending:
                            connection.sendall(outgoing.read())
                        break
                    except ssl.SSLWantReadError:
                        if outgoing.pending:
                            connection.sendall(outgoing.read())
                        incoming.write(connection.recv(65536))
                channel.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
                record = outgoing.read()
                connection.sendall(record[:3])
            entered.set()
            release.wait(3)
        finally:
            connection.close()
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    if cancelled:
        def abort():
            entered.wait(2)
            signal.set()
        canceller = threading.Thread(target=abort, daemon=True)
        canceller.start()
    try:
        llm = LLMService(api_key="local-only", base_url="https://127.0.0.1:{}".format(listener.getsockname()[1]))
        started = time.monotonic()
        with pytest.raises(LlmError) as caught:
            list(llm.chat_completion_stream([], model="test", signal=signal, streamIdleTimeoutMs=2000 if cancelled else 150))
        assert caught.value.code == ("ABORTED" if cancelled else "TIMEOUT")
        assert time.monotonic() - started < 1
        assert not any(t.name == "dsh-http-cancellation" for t in threading.enumerate())
    finally:
        release.set()
        worker.join(1)
        listener.close()
        if cancelled:
            canceller.join(1)


def test_cancellation_bounds_dns_wait_without_leaving_a_transport(monkeypatch):
    import socket
    entered, release, signal = threading.Event(), threading.Event(), threading.Event()
    original = socket.getaddrinfo
    def resolve(*args, **kwargs):
        entered.set()
        release.wait(2)
        return original("127.0.0.1", 1, 0, socket.SOCK_STREAM)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    def abort():
        entered.wait(1)
        signal.set()
    canceller = threading.Thread(target=abort, daemon=True)
    canceller.start()
    try:
        llm = LLMService(api_key="local-only", base_url="http://127.0.0.1:1")
        start = time.monotonic()
        with pytest.raises(LlmError) as caught:
            list(llm.chat_completion_stream([], model="test", signal=signal))
        assert caught.value.code == "ABORTED"
        assert time.monotonic() - start < 1
    finally:
        release.set()
        canceller.join(1)
        for thread in threading.enumerate():
            if thread.name == "dsh-http-dns":
                thread.join(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_close", [False, True])
async def test_stopping_consumer_drains_reader_without_cancelling_caller(server, explicit_close):
    import asyncio
    from dsh.llm.stream_bridge import OwnedStream, iter_chunks
    llm, state = server
    caller = threading.Event()
    state["mode"] = "progress"
    stream = OwnedStream(lambda signal: llm.chat_completion_stream([], model="test", signal=signal), caller)
    reader = iter_chunks(stream)
    assert (await reader.__anext__())["type"] == "block-start"
    assert (await reader.__anext__())["type"] == "text-delta"
    if explicit_close:
        await asyncio.wait_for(reader.aclose(), 1)
    else:
        pending = asyncio.create_task(reader.__anext__())
        await asyncio.sleep(0.03)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1)
    assert not caller.is_set()
    assert not any(t.name in ("dsh-model-reader", "dsh-http-cancellation") for t in threading.enumerate())


@pytest.mark.asyncio
async def test_idle_timeout_excludes_consumer_backpressure(server):
    import asyncio
    from dsh.llm.stream_bridge import OwnedStream, iter_chunks
    llm, state = server
    state["mode"] = "progress"
    reader = iter_chunks(OwnedStream(lambda signal: llm.chat_completion_stream(
        [], model="test", signal=signal, streamIdleTimeoutMs=80)))
    try:
        assert (await reader.__anext__())["type"] == "block-start"
        await asyncio.sleep(0.15)
        assert (await reader.__anext__())["type"] == "text-delta"
        # Only the next demanded network read starts the idle deadline.
        with pytest.raises(LlmError) as caught:
            await reader.__anext__()
        assert caught.value.code == "TIMEOUT"
    finally:
        await reader.aclose()
