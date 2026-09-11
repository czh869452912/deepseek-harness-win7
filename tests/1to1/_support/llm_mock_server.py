"""
Scriptable OpenAI-compatible HTTP/SSE server for transport, protocol, and
semantic-empty LLM recovery tests. Each accepted chat-completions request
consumes one behavior; the server never retries or interprets harness policy.

Ported 1:1 from reference packages/test-support/llm-mock-server/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import http.server
import json
import math
import os
import secrets
import select
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
from urllib.parse import urlparse

MOCK_LLM_BEHAVIORS = (
    "connection_reset",
    "stream_disconnect",
    "empty",
    "empty_body",
    "stream_eof",
    "partial_eof",
    "partial_disconnect",
    "stall",
    "malformed_json",
    "malformed_event",
    "wrong_content_type",
    "rate_limit",
    "server_error",
    "service_unavailable",
    "auth_error",
    "invalid_request",
    "context_overflow",
    "quota_exceeded",
    "success",
    "reasoning_success",
    "tool_call_success",
    "max_tokens",
    "slow_success",
    "random",
)

DEFAULT_MOCK_LLM_RANDOM_WEIGHTS: Dict[str, int] = {
    "success": 48,
    "slow_success": 10,
    "max_tokens": 2,
    "connection_reset": 5,
    "stream_disconnect": 5,
    "partial_disconnect": 10,
    "empty": 5,
    "stall": 2,
    "rate_limit": 5,
    "server_error": 4,
    "service_unavailable": 2,
    "partial_eof": 1,
    "malformed_json": 1,
}

MAX_MOCK_LLM_TIMER_DELAY_MS = 2_147_483_647
DEFAULT_SUCCESS_TEXT = "mock response recovered"
DEFAULT_PARTIAL_TEXT = "discarded partial response"
DEFAULT_REASONING_TEXT = "mock reasoning"
CONCRETE_BEHAVIORS: Set[str] = set(b for b in MOCK_LLM_BEHAVIORS if b != "random")


def _bounded_integer(name: str, value: Any, min_val: int, max_val: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < min_val or value > max_val:
        raise ValueError(f"llm-mock-server: {name} must be an integer between {min_val} and {max_val}")
    return value


def _js_imul(a: int, b: int) -> int:
    val = (a * b) & 0xFFFFFFFF
    return val if val < 0x80000000 else val - 0x100000000


def seeded_random(seed: int) -> Callable[[], float]:
    state = seed & 0xFFFFFFFF

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        mixed = state
        mixed = _js_imul(mixed ^ (mixed >> 15), mixed | 1) & 0xFFFFFFFF
        mixed = (mixed ^ (mixed + _js_imul(mixed ^ (mixed >> 7), mixed | 61))) & 0xFFFFFFFF
        return ((mixed ^ (mixed >> 14)) & 0xFFFFFFFF) / float(0x100000000)

    return draw


def _split_text(text: str, size: int) -> List[str]:
    chunks = []
    for i in range(0, len(text), size):
        chunks.append(text[i : i + size])
    return chunks


def _terminal_chunk(reason: str, output_tokens: int) -> Dict[str, Any]:
    return {
        "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": reason}],
        "usage": {"prompt_tokens": 3, "completion_tokens": output_tokens},
    }


class MockLlmRequestRecord:
    def __init__(
        self,
        attempt: int,
        script_behavior: str,
        behavior: str,
        path: str,
        headers: Dict[str, str],
        body: Any,
    ):
        self.attempt = attempt
        self.scriptBehavior = script_behavior
        self.behavior = behavior
        self.path = path
        self.headers = headers
        self.body = body
        self.chunksSent = 0
        self.outcome: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)


class _ResolvedOptions:
    def __init__(self, options: Dict[str, Any]):
        host = options.get("host", "127.0.0.1")
        port = _bounded_integer("port", options.get("port", 0), 0, 65535)
        chunk_size = _bounded_integer("chunkSize", options.get("chunkSize", 8), 1, 0x1FFFFFFFFFFFFF)
        chunk_delay_ms = _bounded_integer("chunkDelayMs", options.get("chunkDelayMs", 25), 0, MAX_MOCK_LLM_TIMER_DELAY_MS)
        disconnect_delay_ms = _bounded_integer("disconnectDelayMs", options.get("disconnectDelayMs", 10), 0, MAX_MOCK_LLM_TIMER_DELAY_MS)
        retry_after_ms = _bounded_integer("retryAfterMs", options.get("retryAfterMs", 1000), 1, MAX_MOCK_LLM_TIMER_DELAY_MS)

        raw_seed = options.get("randomSeed")
        if raw_seed is None:
            raw_seed = secrets.randbits(32)
        random_seed = _bounded_integer("randomSeed", raw_seed, 0, 0xFFFFFFFF)

        success_text = options.get("successText", DEFAULT_SUCCESS_TEXT)
        partial_text = options.get("partialText", DEFAULT_PARTIAL_TEXT)
        reasoning_text = options.get("reasoningText", DEFAULT_REASONING_TEXT)
        tool_name = options.get("toolName", "mock_tool")
        tool_arguments = options.get("toolArguments", '{"value":"mock"}')

        if not host:
            raise ValueError("llm-mock-server: host must not be empty")
        seq = options.get("sequence")
        if not seq or len(seq) == 0:
            raise ValueError("llm-mock-server: sequence must not be empty")
        last_behavior = seq[-1]

        api_key = options.get("apiKey")
        if api_key == "":
            raise ValueError("llm-mock-server: apiKey must not be empty")

        if not success_text:
            raise ValueError("llm-mock-server: successText must not be empty")
        if not partial_text:
            raise ValueError("llm-mock-server: partialText must not be empty")
        if not reasoning_text:
            raise ValueError("llm-mock-server: reasoningText must not be empty")
        if not tool_name:
            raise ValueError("llm-mock-server: toolName must not be empty")

        request_id = options.get("requestId")
        if request_id == "":
            raise ValueError("llm-mock-server: requestId must not be empty")

        try:
            json.loads(tool_arguments)
        except Exception:
            raise ValueError("llm-mock-server: toolArguments must be valid JSON")

        cfg_weights = options.get("randomWeights") or DEFAULT_MOCK_LLM_RANDOM_WEIGHTS
        weights_list: List[Tuple[str, float]] = []
        for beh, w in cfg_weights.items():
            if beh not in CONCRETE_BEHAVIORS:
                raise ValueError(f"llm-mock-server: randomWeights contains unknown concrete behavior {json.dumps(beh)}")
            if not isinstance(w, (int, float)) or isinstance(w, bool) or math.isnan(w) or math.isinf(w) or w < 0:
                raise ValueError(f"llm-mock-server: random weight for {beh} must be a non-negative finite number")
            if w > 0:
                weights_list.append((beh, float(w)))

        if not weights_list:
            raise ValueError("llm-mock-server: randomWeights must contain at least one positive weight")

        self.host = host
        self.port = port
        self.apiKey = api_key
        self.sequence = list(seq)
        self.lastBehavior = last_behavior
        self.repeatLast = bool(options.get("repeatLast", False))
        self.randomSeed = random_seed
        self.randomWeights = weights_list
        self.successText = success_text
        self.partialText = partial_text
        self.reasoningText = reasoning_text
        self.chunkSize = chunk_size
        self.chunkDelayMs = chunk_delay_ms
        self.disconnectDelayMs = disconnect_delay_ms
        self.retryAfterMs = retry_after_ms
        self.requestId = request_id
        self.toolName = tool_name
        self.toolArguments = tool_arguments
        self.onEvent = options.get("onEvent")


class _MockLlmHttpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, is_ipv6=False):
        if is_ipv6:
            self.address_family = socket.AF_INET6
        super().__init__(server_address, RequestHandlerClass)
        self.active_sockets: Set[socket.socket] = set()
        self.sockets_lock = threading.Lock()

    def register_socket(self, sock: socket.socket) -> None:
        with self.sockets_lock:
            self.active_sockets.add(sock)

    def unregister_socket(self, sock: socket.socket) -> None:
        with self.sockets_lock:
            self.active_sockets.discard(sock)

    def force_close_all_connections(self) -> None:
        with self.sockets_lock:
            for sock in list(self.active_sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass
            self.active_sockets.clear()


class _MockLlmHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress default noisy stdlib logging

    def setup(self) -> None:
        super().setup()
        self.server.register_socket(self.connection)

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            self.server.unregister_socket(self.connection)

    def _safe_emit(self, event: Dict[str, Any]) -> None:
        on_event = self.server.resolved.onEvent
        if callable(on_event):
            try:
                on_event(dict(event))
            except Exception:
                pass

    def _finish_record(self, record: MockLlmRequestRecord, outcome: str) -> None:
        if record.outcome is not None:
            return
        record.outcome = outcome
        self._safe_emit({
            "type": "result",
            "attempt": record.attempt,
            "scriptBehavior": record.scriptBehavior,
            "behavior": record.behavior,
            "outcome": outcome,
            "chunksSent": record.chunksSent,
        })

    def _write_raw(self, data: bytes) -> bool:
        try:
            self.wfile.write(data)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _open_sse(self, content_type: str = "text/event-stream; charset=utf-8") -> bool:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        return True

    def _write_chunk(self, data: bytes) -> bool:
        if not data:
            return True
        chunk_header = f"{len(data):X}\r\n".encode("ascii")
        return self._write_raw(chunk_header + data + b"\r\n")

    def _write_sse(self, record: MockLlmRequestRecord, payload: Any) -> bool:
        payload_str = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        line = f"data: {payload_str}\n\n".encode("utf-8")
        ok = self._write_chunk(line)
        if ok:
            record.chunksSent += 1
        return ok

    def _write_done(self, record: MockLlmRequestRecord) -> bool:
        return self._write_sse(record, "[DONE]")

    def _end_response(self) -> bool:
        return self._write_raw(b"0\r\n\r\n")

    def _http_error(self, record: MockLlmRequestRecord, status: int, message: str, code: str, error_type: str = "mock_error") -> None:
        self._finish_record(record, "completed")
        body = json.dumps({"error": {"message": message, "type": error_type, "code": code}}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if record.behavior == "rate_limit":
            self.send_header("Retry-After", str(math.ceil(self.server.resolved.retryAfterMs / 1000.0)))
        if self.server.resolved.requestId is not None:
            self.send_header("X-Request-Id", self.server.resolved.requestId)
        self.end_headers()
        self._write_raw(body)



    def _pause(self, milliseconds: int) -> bool:
        if milliseconds <= 0:
            return True
        # Check if socket is still alive while waiting
        delay_sec = milliseconds / 1000.0
        deadline = time.time() + delay_sec
        sock = self.connection
        while time.time() < deadline:
            remaining = max(0.001, deadline - time.time())
            # Poll for readability; if readable but returns empty bytes, client disconnected
            r, _, _ = select.select([sock], [], [], min(remaining, 0.05))
            if r:
                try:
                    peek = sock.recv(1, socket.MSG_PEEK)
                    if not peek:
                        return False
                except Exception:
                    return False
        return True

    def _stream_text(self, record: MockLlmRequestRecord, text: str, delay_ms: int) -> bool:
        for chunk in _split_text(text, self.server.resolved.chunkSize):
            payload = {"choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]}
            if not self._write_sse(record, payload):
                return False
            if delay_ms > 0:
                if not self._pause(delay_ms):
                    return False
        return True

    def _complete_text(self, record: MockLlmRequestRecord, reason: str, delay_ms: int) -> None:
        if not self._stream_text(record, self.server.resolved.successText, delay_ms):
            self._finish_record(record, "client_closed")
            return
        if not self._write_sse(record, _terminal_chunk(reason, len(self.server.resolved.successText))):
            self._finish_record(record, "client_closed")
            return
        if not self._write_done(record):
            self._finish_record(record, "client_closed")
            return
        self._finish_record(record, "completed")
        self._end_response()




    def _destroy_socket(self) -> None:
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except Exception:
            pass
        try:
            self.connection.close()
        except Exception:
            pass

    def _disconnect(self, record: MockLlmRequestRecord) -> None:
        if not self._pause(self.server.resolved.disconnectDelayMs):
            self._finish_record(record, "client_closed")
            return
        self._finish_record(record, "reset")
        self._destroy_socket()

    def _tool_call_chunks(self) -> List[Dict[str, Any]]:
        midpoint = max(1, len(self.server.resolved.toolArguments) // 2)
        return [
            {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "id": "mock-call-1",
                            "type": "function",
                            "function": {
                                "name": self.server.resolved.toolName,
                                "arguments": self.server.resolved.toolArguments[:midpoint],
                            },
                        }],
                    },
                    "finish_reason": None,
                }],
            },
            {
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {
                                "arguments": self.server.resolved.toolArguments[midpoint:],
                            },
                        }],
                    },
                    "finish_reason": None,
                }],
            },
        ]

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        expected_key = self.server.resolved.apiKey
        if expected_key is not None:
            auth = self.headers.get("Authorization") or self.headers.get("authorization")
            if auth != f"Bearer {expected_key}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self._write_raw(json.dumps({"error": {"message": "invalid mock bearer token", "code": "invalid_api_key"}}).encode("utf-8"))
                return

        content_len_header = self.headers.get("Content-Length") or self.headers.get("content-length")
        raw_body = b""
        if content_len_header:
            try:
                length = int(content_len_header)
                raw_body = self.rfile.read(length)
            except Exception:
                raw_body = b""
        else:
            # Chunked or empty
            encoding = self.headers.get("Transfer-Encoding") or self.headers.get("transfer-encoding")
            if encoding == "chunked":
                chunks = []
                while True:
                    line = self.rfile.readline()
                    if not line:
                        break
                    chunk_len = int(line.strip().split(b";")[0], 16)
                    if chunk_len == 0:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(chunk_len))
                    self.rfile.readline()
                raw_body = b"".join(chunks)

        body: Any = None
        if raw_body:
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self._write_raw(json.dumps({"error": {"message": "request body must be valid JSON", "code": "invalid_json"}}).encode("utf-8"))
                return

        with self.server.lock:
            selected_script_behavior, concrete_behavior = self.server.select_behavior()
            attempt = len(self.server.requests) + 1
            record = MockLlmRequestRecord(
                attempt=attempt,
                script_behavior=selected_script_behavior,
                behavior=concrete_behavior,
                path=path,
                headers={k.lower(): v for k, v in self.headers.items()},
                body=body,
            )
            self.server.requests.append(record)

        self._safe_emit({
            "type": "request",
            "attempt": record.attempt,
            "scriptBehavior": record.scriptBehavior,
            "behavior": record.behavior,
            "path": path,
        })

        try:
            self._execute_behavior(record)
        except Exception:
            if record.outcome is None:
                self._finish_record(record, "server_error")

    def do_GET(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def do_PUT(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def do_DELETE(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def _execute_behavior(self, record: MockLlmRequestRecord) -> None:
        b = record.behavior
        if b == "script_exhausted":
            self._http_error(record, 500, "mock script exhausted", "MOCK_SCRIPT_EXHAUSTED")
            return
        elif b == "connection_reset":
            self._finish_record(record, "reset")
            self._destroy_socket()
            return
        elif b == "stream_disconnect":
            self._open_sse()
            self._disconnect(record)
            return
        elif b == "empty":
            self._open_sse()
            self._write_sse(record, _terminal_chunk("stop", 0))
            self._write_done(record)
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "empty_body":
            self._open_sse()
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "stream_eof":
            self._open_sse()
            self._write_sse(record, {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "partial_eof":
            self._open_sse()
            self._stream_text(record, self.server.resolved.partialText, 0)
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "partial_disconnect":
            self._open_sse()
            if not self._stream_text(record, self.server.resolved.partialText, self.server.resolved.chunkDelayMs):
                self._finish_record(record, "client_closed")
                return
            self._disconnect(record)
            return
        elif b == "stall":
            self._finish_record(record, "stalled")
            self._open_sse()

            # Keep connection open until closed by client or server
            while True:
                if not self._pause(1000):
                    break
            return
        elif b == "malformed_json":
            self._open_sse()
            self._write_chunk(b"data: {not-json\n\n")
            record.chunksSent += 1
            self._write_done(record)
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "malformed_event":
            self._open_sse()
            self._write_sse(record, {"choices": [None]})
            self._write_done(record)
            self._finish_record(record, "completed")
            self._end_response()
            return
        elif b == "wrong_content_type":
            self._open_sse("application/json")
            self._complete_text(record, "stop", 0)
            return
        elif b == "rate_limit":
            self._http_error(record, 429, "mock rate limit", "rate_limit")
            return
        elif b == "server_error":
            self._http_error(record, 500, "mock server error", "server_error")
            return
        elif b == "service_unavailable":
            self._http_error(record, 503, "mock service unavailable", "service_unavailable")
            return
        elif b == "auth_error":
            self._http_error(record, 401, "mock authentication failed", "invalid_api_key")
            return
        elif b == "invalid_request":
            self._http_error(record, 400, "mock invalid request", "invalid_request")
            return
        elif b == "context_overflow":
            self._http_error(record, 400, "mock input exceeds the model context window", "context_length_exceeded", "invalid_request_error")
            return
        elif b == "quota_exceeded":
            self._http_error(record, 429, "mock insufficient quota", "insufficient_quota")
            return
        elif b == "success":
            self._open_sse()
            self._complete_text(record, "stop", 0)
            return
        elif b == "reasoning_success":
            self._open_sse()
            for chunk in _split_text(self.server.resolved.reasoningText, self.server.resolved.chunkSize):
                if not self._write_sse(record, {"choices": [{"index": 0, "delta": {"reasoning_content": chunk}, "finish_reason": None}]}):
                    self._finish_record(record, "client_closed")
                    return
            self._complete_text(record, "stop", 0)
            return
        elif b == "tool_call_success":
            self._open_sse()
            for chunk in self._tool_call_chunks():
                if not self._write_sse(record, chunk):
                    self._finish_record(record, "client_closed")
                    return
            if not self._write_sse(record, _terminal_chunk("tool_calls", 2)):
                self._finish_record(record, "client_closed")
                return
            if not self._write_done(record):
                self._finish_record(record, "client_closed")
                return
            self._end_response()
            self._finish_record(record, "completed")
            return

        elif b == "max_tokens":
            self._open_sse()
            self._complete_text(record, "length", 0)
            return
        elif b == "slow_success":
            self._open_sse()
            self._complete_text(record, "stop", self.server.resolved.chunkDelayMs)
            return


class _CloseAwaiter:
    def __init__(self, close_fn: Callable[[], None]):
        self._close_fn = close_fn

    def __await__(self):
        async def _run():
            self._close_fn()
        return _run().__await__()

    def __call__(self) -> None:
        self._close_fn()


class MockLlmServer:
    """
    Running scriptable mock LLM server.
    """

    def __init__(self, resolved: _ResolvedOptions):
        self.resolved = resolved
        self.requests: List[MockLlmRequestRecord] = []
        self.randomSeed = resolved.randomSeed
        self.lock = threading.Lock()
        self._cursor = 0
        self._random_fn = seeded_random(resolved.randomSeed)
        self._closed = False

        is_ipv6 = ":" in resolved.host
        self._httpd = _MockLlmHttpServer(
            (resolved.host, resolved.port),
            _MockLlmHandler,
            is_ipv6=is_ipv6,
        )
        self._httpd.resolved = resolved
        self._httpd.requests = self.requests
        self._httpd.lock = self.lock
        self._httpd.select_behavior = self._select_behavior

        self.port = self._httpd.server_address[1]
        advertised_host = f"[{resolved.host}]" if is_ipv6 else resolved.host
        self.baseURL = f"http://{advertised_host}:{self.port}"

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _choose_random_behavior(self) -> str:
        total = sum(w for _, w in self.resolved.randomWeights)
        draw = self._random_fn() * total
        for behavior, weight in self.resolved.randomWeights:
            if draw < weight:
                return behavior
            draw -= weight
        return self.resolved.randomWeights[-1][0]

    def _select_behavior(self) -> Tuple[str, str]:
        if self._cursor < len(self.resolved.sequence):
            selected = self.resolved.sequence[self._cursor]
        else:
            selected = self.resolved.lastBehavior if self.resolved.repeatLast else "script_exhausted"
        self._cursor += 1

        concrete = self._choose_random_behavior() if selected == "random" else selected
        return selected, concrete

    def _close_internal(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._httpd.force_close_all_connections()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2.0)

    def close(self) -> _CloseAwaiter:
        return _CloseAwaiter(self._close_internal)

    def __enter__(self) -> "MockLlmServer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._close_internal()


def start_mock_llm_server(options: Optional[Dict[str, Any]] = None, **kwargs: Any) -> MockLlmServer:
    opts = dict(options or {})
    opts.update(kwargs)
    resolved = _ResolvedOptions(opts)
    server = MockLlmServer(resolved)
    return server


startMockLlmServer = start_mock_llm_server
