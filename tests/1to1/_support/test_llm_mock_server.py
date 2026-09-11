"""
1:1 Parity Tests for Mock LLM Server wire behaviors and option validation.
Ported from reference packages/test-support/llm-mock-server/tests/server.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import http.client
import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pytest

from .llm_mock_server import (
    MockLlmServer,
    start_mock_llm_server,
    startMockLlmServer,
)


@pytest.fixture
def running():
    servers: List[MockLlmServer] = []
    yield servers
    for server in servers:
        server.close()()


def start(running_list: List[MockLlmServer], sequence: List[str], **options: Any) -> MockLlmServer:
    server = start_mock_llm_server(sequence=sequence, **options)
    running_list.append(server)
    return server


def chat(
    server: MockLlmServer,
    path: Optional[str] = None,
    key: Optional[str] = None,
    body: Optional[str] = None,
    timeout: float = 5.0,
) -> urllib.request.addinfourl:
    url = f"{server.baseURL}{path if path is not None else '/v1/chat/completions'}"
    headers = {"content-type": "application/json"}
    if key is not None:
        headers["authorization"] = f"Bearer {key}"
    data = (body if body is not None else json.dumps({"model": "mock", "messages": [], "stream": True})).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


def raw_chat(server: MockLlmServer, chunks: List[bytes]) -> None:
    parsed = urlparse(server.baseURL)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5.0)
    conn.putrequest("POST", "/v1/chat/completions")
    conn.putheader("content-type", "application/json")
    conn.putheader("transfer-encoding", "chunked")
    conn.endheaders()
    for chunk in chunks:
        conn.send(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
    conn.send(b"0\r\n\r\n")
    resp = conn.getresponse()
    resp.read()
    conn.close()


def test_streams_complete_text_response_and_captures_request(running):
    events: List[Dict[str, Any]] = []
    server = start(
        running,
        ["success"],
        apiKey="mock-key",
        successText="recovered",
        chunkSize=3,
        onEvent=lambda ev: events.append(ev),
    )

    resp = chat(server, key="mock-key")
    body = resp.read().decode("utf-8")

    assert resp.status == 200
    assert "text/event-stream" in resp.headers.get("content-type")
    assert '"content":"rec"' in body
    assert '"content":"ove"' in body
    assert '"content":"red"' in body
    assert '"finish_reason":"stop"' in body
    assert "data: [DONE]" in body

    assert len(server.requests) == 1
    req = server.requests[0]
    assert req.attempt == 1
    assert req.behavior == "success"
    assert req.path == "/v1/chat/completions"
    assert req.body == {"model": "mock", "messages": [], "stream": True}
    assert req.chunksSent == 5
    assert req.outcome == "completed"

    assert events == [
        {
            "type": "request",
            "attempt": 1,
            "scriptBehavior": "success",
            "behavior": "success",
            "path": "/v1/chat/completions",
        },
        {
            "type": "result",
            "attempt": 1,
            "scriptBehavior": "success",
            "behavior": "success",
            "outcome": "completed",
            "chunksSent": 5,
        },
    ]


def test_supports_root_paths_and_intentionally_ignores_telemetry_observer_failures(running):
    def bad_observer(ev):
        raise RuntimeError("observer failed")

    server = start(running, ["empty"], onEvent=bad_observer)
    resp = chat(server, path="/chat/completions")

    assert resp.status == 200
    body = resp.read().decode("utf-8")
    assert "data: [DONE]" in body
    assert server.requests[0].path == "/chat/completions"
    assert server.requests[0].outcome == "completed"


@pytest.mark.parametrize("behavior,chunks,marker", [
    ("empty_body", 0, ""),
    ("stream_eof", 1, '"role":"assistant"'),
    ("partial_eof", 1, "discarded partial response"),
    ("malformed_json", 2, "data: {not-json"),
    ("malformed_event", 2, '"choices":[null]'),
])
def test_serves_markers_without_inventing_terminal_completion(running, behavior, chunks, marker):
    server = start(running, [behavior], chunkSize=100)
    resp = chat(server)
    body = resp.read().decode("utf-8")

    assert resp.status == 200
    assert marker in body
    if behavior not in ("malformed_json", "malformed_event"):
        assert "[DONE]" not in body
    assert server.requests[0].behavior == behavior
    assert server.requests[0].chunksSent == chunks
    assert server.requests[0].outcome == "completed"


@pytest.mark.parametrize("behavior,receives_headers", [
    ("connection_reset", False),
    ("stream_disconnect", True),
    ("partial_disconnect", True),
])
def test_forces_transport_boundary(running, behavior, receives_headers):
    server = start(running, [behavior], disconnectDelayMs=20, partialText="half")

    headers_received = False
    with pytest.raises(Exception):
        resp = chat(server, timeout=2.0)
        headers_received = True
        resp.read()

    assert headers_received == receives_headers
    assert server.requests[0].behavior == behavior
    expected_chunks = 1 if behavior == "partial_disconnect" else 0
    assert server.requests[0].chunksSent == expected_chunks
    assert server.requests[0].outcome == "reset"


def test_holds_stalled_stream_until_client_aborts_and_close_remains_idempotent(running):
    server = start(running, ["stall"])
    parsed = urlparse(server.baseURL)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5.0)
    conn.request("POST", "/v1/chat/completions", body=b'{"model":"mock"}', headers={"content-type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert server.requests[0].behavior == "stall"
    assert server.requests[0].outcome == "stalled"
    conn.close()
    server.close()()
    server.close()()


@pytest.mark.parametrize("behavior,delay_ms", [
    ("slow_success", 100),
    ("stream_disconnect", 100),
    ("partial_disconnect", 100),
])
def test_records_client_that_closes_during_streaming(running, behavior, delay_ms):
    events: List[Dict[str, Any]] = []
    server = start(
        running,
        [behavior],
        chunkDelayMs=delay_ms,
        disconnectDelayMs=delay_ms,
        chunkSize=1,
        onEvent=lambda ev: events.append(ev),
    )

    parsed = urlparse(server.baseURL)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5.0)
    conn.request("POST", "/v1/chat/completions", body=b'{"model":"mock"}', headers={"content-type": "application/json"})
    resp = conn.getresponse()
    conn.close()

    # Give server thread moment to detect close

    import time
    time.sleep(0.3)

    assert server.requests[0].behavior == behavior
    assert server.requests[0].outcome == "client_closed"
    result_events = [ev for ev in events if ev.get("type") == "result"]
    assert len(result_events) >= 1
    assert result_events[0]["outcome"] == "client_closed"


def test_preserves_utf8_code_points_split_across_request_chunks(running):
    server = start(running, ["success"])
    encoded = json.dumps({"messages": [{"role": "user", "content": "\u4f60\u597d"}]}, ensure_ascii=False).encode("utf-8")
    char_offset = encoded.find("\u4f60".encode("utf-8"))

    assert char_offset >= 0

    raw_chat(server, [
        encoded[: char_offset + 1],
        encoded[char_offset + 1 :],
    ])

    assert server.requests[0].body == {"messages": [{"role": "user", "content": "\u4f60\u597d"}]}



def test_formats_ipv6_listener_as_valid_base_url(running):
    try:
        server = start(running, ["success"], host="::1")
    except Exception:
        pytest.skip("IPv6 loopback not supported on this environment")

    assert re.match(r"^http://\[::1\]:\d+$", server.baseURL)
    resp = chat(server)
    assert resp.status == 200


def test_emits_reasoning_tool_calls_max_token_finishes_slow_chunks_and_wrong_content_type(running):
    server = start(
        running,
        [
            "reasoning_success",
            "tool_call_success",
            "max_tokens",
            "slow_success",
            "wrong_content_type",
        ],
        successText="answer",
        reasoningText="think",
        toolName="lookup",
        toolArguments='{"id":7}',
        chunkDelayMs=1,
        chunkSize=2,
    )

    bodies: List[str] = []
    content_types: List[str] = []
    for _ in range(5):
        resp = chat(server)
        content_types.append(resp.headers.get("content-type"))
        bodies.append(resp.read().decode("utf-8"))

    assert '"reasoning_content":"th"' in bodies[0]
    assert '"name":"lookup"' in bodies[1]
    assert '"arguments":"{\\"id"' in bodies[1]
    assert '"finish_reason":"tool_calls"' in bodies[1]
    assert '"finish_reason":"length"' in bodies[2]
    assert '"finish_reason":"stop"' in bodies[3]
    assert "application/json" in content_types[4]
    assert len(server.requests) == 5
    assert all(r.outcome == "completed" for r in server.requests)


@pytest.mark.parametrize("behavior,status,marker", [
    ("rate_limit", 429, "mock rate limit"),
    ("server_error", 500, "mock server error"),
    ("service_unavailable", 503, "mock service unavailable"),
    ("auth_error", 401, "mock authentication failed"),
    ("invalid_request", 400, "mock invalid request"),
    ("context_overflow", 400, "context_length_exceeded"),
    ("quota_exceeded", 429, "insufficient_quota"),
])
def test_serves_structured_http_errors(running, behavior, status, marker):
    server = start(running, [behavior], retryAfterMs=1001, requestId="mock-request-1")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        chat(server)

    err = exc_info.value
    body = err.read().decode("utf-8")

    assert err.code == status
    assert marker in body
    assert err.headers.get("x-request-id") == "mock-request-1"
    if behavior == "rate_limit":
        assert err.headers.get("retry-after") == "2"
    else:
        assert err.headers.get("retry-after") is None
    assert server.requests[0].outcome == "completed"


def test_fails_loud_on_script_exhaustion_and_can_explicitly_repeat_final_behavior(running):
    exhausted = start(running, ["success"], successText="once")
    chat(exhausted).read()
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        chat(exhausted)
    err = exc_info.value
    assert err.code == 500
    assert "mock script exhausted" in err.read().decode("utf-8")
    assert [r.behavior for r in exhausted.requests] == ["success", "script_exhausted"]

    repeating = start(running, ["empty"], repeatLast=True)
    chat(repeating).read()
    chat(repeating).read()
    assert [r.behavior for r in repeating.requests] == ["empty", "empty"]


def test_selects_weighted_random_behaviors_reproducibly_and_reports_concrete_choice(running):
    options = {
        "sequence": ["random"],
        "repeatLast": True,
        "randomSeed": 42,
        "randomWeights": {"success": 1, "empty": 1},
        "successText": "random success",
    }
    first = start_mock_llm_server(**options)
    second = start_mock_llm_server(**options)
    running.extend([first, second])

    for _ in range(12):
        chat(first).read()
        chat(second).read()

    first_choices = [r.behavior for r in first.requests]
    assert first.randomSeed == 42
    assert second.randomSeed == 42
    assert first_choices == [r.behavior for r in second.requests]
    assert set(first_choices) == {"success", "empty"}
    assert all(r.scriptBehavior == "random" for r in first.requests)


def test_rejects_invalid_method_route_bearer_token_and_json_without_consuming_script(running):
    server = start(running, ["success"], apiKey="expected")

    # Method != POST -> 405
    req = urllib.request.Request(f"{server.baseURL}/v1/chat/completions", method="GET")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 405
    assert exc_info.value.headers.get("allow") == "POST"

    # Route != /chat/completions -> 404
    req = urllib.request.Request(f"{server.baseURL}/v1/other", data=b"{}", headers={"content-type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 404

    # Auth mismatch -> 401
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        chat(server, key="wrong")
    assert exc_info.value.code == 401

    # Invalid JSON -> 400
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        chat(server, key="expected", body="{")
    assert exc_info.value.code == 400

    assert len(server.requests) == 0

    # Empty body request
    req = urllib.request.Request(
        f"{server.baseURL}/v1/chat/completions",
        data=b"",
        headers={"authorization": "Bearer expected"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 200
    assert server.requests[0].behavior == "success"
    assert server.requests[0].body is None


@pytest.mark.parametrize("options,expected_pattern", [
    ({"sequence": []}, r"sequence"),
    ({"sequence": ["success"], "host": ""}, r"host"),
    ({"sequence": ["success"], "port": -1}, r"port"),
    ({"sequence": ["success"], "port": 65536}, r"port"),
    ({"sequence": ["success"], "apiKey": ""}, r"apiKey"),
    ({"sequence": ["success"], "successText": ""}, r"successText"),
    ({"sequence": ["success"], "partialText": ""}, r"partialText"),
    ({"sequence": ["success"], "reasoningText": ""}, r"reasoningText"),
    ({"sequence": ["success"], "chunkSize": 0}, r"chunkSize"),
    ({"sequence": ["success"], "chunkDelayMs": -1}, r"chunkDelayMs"),
    ({"sequence": ["success"], "retryAfterMs": 0}, r"retryAfterMs"),
    ({"sequence": ["success"], "requestId": ""}, r"requestId"),
    ({"sequence": ["success"], "toolName": ""}, r"toolName"),
    ({"sequence": ["success"], "toolArguments": "{"}, r"toolArguments"),
    ({"sequence": ["random"], "randomSeed": -1}, r"randomSeed"),
    ({"sequence": ["random"], "randomWeights": {"random": 1}}, r"unknown concrete behavior"),
    ({"sequence": ["random"], "randomWeights": {"success": -1}}, r"non-negative"),
    ({"sequence": ["random"], "randomWeights": {"success": 0}}, r"positive weight"),
])
def test_rejects_invalid_options(options, expected_pattern):
    with pytest.raises(ValueError, match=expected_pattern):
        start_mock_llm_server(**options)
