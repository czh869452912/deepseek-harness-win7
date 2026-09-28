"""Provider bytes and durable tool history, not an adapter-shaped mock."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from dsh.llm.deepseek_wire import parse_sse, serialize_request, translate
from dsh.llm.llm_service import LLMService, LlmError


def test_history_and_sampling_have_provider_wire_shape():
    body = serialize_request({"model": "selected-model", "system": "selected persona",
        "maxTokens": 42, "reasoningEffort": "high", "tools": [{"name": "read", "parameters": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "inspect"}]},
            {"role": "assistant", "content": [{"type": "reasoning", "text": "thinking"},
                {"type": "tool-call", "id": "c1", "name": "read", "arguments": "{}"}]},
            {"role": "user", "content": [{"type": "tool-result", "toolCallId": "c1",
                                          "content": [{"type": "text", "text": "file content"}]}]}]})
    assert body["messages"] == [
        {"role": "system", "content": "selected persona"}, {"role": "user", "content": "inspect"},
        {"role": "assistant", "content": "", "reasoning_content": "thinking", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "file content"}]
    assert body["tools"][0]["type"] == "function"
    assert body["max_tokens"] == 42
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_sse_fragmented_utf8_crlf_multiline_and_bom():
    raw = '\ufeff: ping\r\ndata: {"choices":\r\ndata: [{"delta":{"content":"中文"},"finish_reason":"stop"}]}\r\n\r\ndata: [DONE]\r\n\r\n'.encode("utf-8")
    chunks = list(translate(parse_sse(bytes([byte]) for byte in raw)))
    assert chunks[-2]["block"] == {"type": "text", "text": "中文"}
    assert chunks[-1] == {"type": "finish", "reason": {"kind": "stop"}}
    assert not any(c["type"] == "usage" for c in chunks)


@pytest.mark.parametrize("raw,code", [
    (b'data: {bad}\n\n', "MALFORMED_RESPONSE"),
    (b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"stop"}]}\n\n', "STREAM_CLOSED"),
    (b'data: [DONE]\n', "STREAM_CLOSED"),
])
def test_malformed_or_truncated_stream_never_completes(raw, code):
    chunks = []
    with pytest.raises(LlmError) as failure:
        for chunk in translate(parse_sse([raw])):
            chunks.append(chunk)
    assert failure.value.code == code
    assert not any(c["type"] in ("finish", "block-end", "usage") for c in chunks)


def test_dynamic_block_order_usage_and_finish():
    payloads = [json.dumps({"choices": [{"delta": {"reasoning_content": "r", "content": "t", "tool_calls": [
        {"index": 7, "id": "c", "function": {"name": "read", "arguments": "{"}}]}}]}),
        json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 7, "function": {"name": "read", "arguments": "}"}}]},
                                 "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                                 "prompt_cache_hit_tokens": 4, "total_tokens": 12}}), "[DONE]"]
    chunks = list(translate(payloads))
    assert [(c["index"], c["blockType"]) for c in chunks if c["type"] == "block-start"] == [(0, "reasoning"), (1, "text"), (2, "tool-call")]
    assert chunks[-3]["block"] == {"type": "tool-call", "name": "read", "id": "c", "arguments": "{}"}
    assert chunks[-2]["usage"] == {"inputTokens": 6, "outputTokens": 2, "cacheReadTokens": 4, "totalTokens": 12}
    assert chunks[-1]["reason"] == {"kind": "tool-calls"}
    assert list(translate(["[DONE]"]))[-1]["reason"]["failure"]["code"] == "EMPTY_RESPONSE"


def test_real_http_transport_passes_options_and_does_not_retry_truncation(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"stop"}]}\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        llm = LLMService()
        monkeypatch.setattr(llm, "resolve_base_url", lambda *_: "http://127.0.0.1:{}".format(server.server_port))
        monkeypatch.setattr(llm, "resolve_api_key", lambda *_: "local-test-only")
        with pytest.raises(LlmError) as error:
            list(llm.chat_completion_stream(messages=[{"role": "user", "content": "hello"}],
                 model="chosen", maxTokens=42, reasoningEffort="off"))
        assert error.value.code == "STREAM_CLOSED"
        assert len(requests) == 1
        assert requests[0]["model"] == "chosen"
        assert requests[0]["max_tokens"] == 42
        assert requests[0]["thinking"] == {"type": "disabled"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
