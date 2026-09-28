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
