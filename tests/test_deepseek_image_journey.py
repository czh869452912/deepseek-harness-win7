import asyncio
import copy
import io
import json
import threading
import time
from types import SimpleNamespace
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from dsh.attachment.local import LocalAttachmentStore
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.llm_service import LlmError


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    state = {"uploads": [], "chats": [], "headers": [], "mode": "normal"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/files":
                mime = BytesParser(policy=policy.default).parsebytes(("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + data)
                part = next(p for p in mime.iter_parts() if p.get_param("name", header="content-disposition") == "file")
                state["uploads"].append(part.get_payload(decode=True))
                if state["mode"] == "fallback":
                    self.reply(503, {"error": {"message": "Files unavailable"}})
                    return
                now = int(time.time())
                self.reply(200, {"object": "file", "id": "file-" + str(len(state["uploads"])), "bytes": len(state["uploads"][-1]),
                                 "purpose": "user_data", "filename": part.get_filename(), "created_at": now, "expires_at": now + 604800})
                return
            state["chats"].append(json.loads(data))
            state["headers"].append({key.lower(): value for key, value in self.headers.items()})
            if state["mode"] == "stale" and len(state["chats"]) == 1:
                self.reply(400, {"error": {"message": "file_id file-1 expired"}})
                return
            if state["mode"] == "reject":
                self.reply(400, {"error": {"message": "bad request"}})
                return
            if state["mode"] == "invalid-image":
                self.reply(400, {"error": {"message": "unsupported image in file-1"}})
                return
            body = b'data: {"choices":[{"delta":{"content":"image understood"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if state["mode"] == "slow-bytes":
                for offset in range(0, len(body), 8):
                    self.wfile.write(body[offset:offset + 8])
                    self.wfile.flush()
                    time.sleep(0.04)
                return
            self.wfile.write(body)
        def reply(self, status, value):
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{}".format(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


async def setup(tmp_path, url):
    ctx = Context()
    ctx.set_service("launchEnvironment", LaunchEnvironmentSnapshot([{"source": "process", "values": {"DEEPSEEK_API_KEY": "local-only"}}]))
    await ctx.plugin(LocalAttachmentStore, config={"dshHome": str(tmp_path)})
    store = ctx.get("attachments")
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(output, "PNG")
    ref = store.save_image({"data": output.getvalue(), "mediaType": "image/png", "name": "red.png"})
    adapter = DeepSeekAdapter(ctx, {"baseURL": url, "models": [{"id": "vision", "inputModalities": ["text", "image"]}]})
    return ctx, adapter, ref


@pytest.mark.asyncio
@pytest.mark.parametrize("extensions", [False, True])
async def test_native_request_identity_headers_are_stable_and_purpose_scoped(tmp_path, endpoint, extensions):
    from dsh.llm.stream_bridge import iter_chunks
    url, state = endpoint
    ctx = Context()
    ctx.set_service("launchEnvironment", LaunchEnvironmentSnapshot([{"source": "process", "values": {"DEEPSEEK_API_KEY": "local-only"}}]))
    if extensions:
        await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    adapter = DeepSeekAdapter(ctx, {"baseURL": url})
    try:
        for extra in ({"sessionId": "s1", "purpose": "compaction"}, {"sessionId": "s2", "purpose": "session-title"}, {}):
            chunks = [chunk async for chunk in iter_chunks(adapter.stream(dict(extra, model="deepseek-v4-flash", messages=[])))]
            assert chunks[-1]["type"] == "finish"
        headers = state["headers"]
        persisted = (tmp_path / ".anonymous-user-id").read_text(encoding="utf-8").strip()
        assert all(row["x-deepseek-harness-user-id"] == persisted for row in headers)
        assert headers[0]["x-deepseek-harness-session-id"] == "s1"
        assert headers[0]["x-deepseek-harness-compact"] == "1"
        assert headers[1]["x-deepseek-harness-session-id"] == "s2"
        assert "x-deepseek-harness-compact" not in headers[1]
        assert "x-deepseek-harness-session-id" not in headers[2]
        assert "x-deepseek-harness-compact" not in headers[2]
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_extension_request_idle_watchdog_tracks_partial_wire_activity(tmp_path, endpoint):
    url, state = endpoint
    state["mode"] = "slow-bytes"
    ctx, adapter, _ = await setup(tmp_path, url)
    adapter.config["streamIdleTimeoutMs"] = 250
    try:
        chunks = [chunk async for chunk in adapter.stream({"model": "vision", "messages": []})]
        assert chunks[-1]["type"] == "finish"
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_extension_idle_watchdog_does_not_charge_settled_reader_delivery(tmp_path, endpoint, monkeypatch):
    from dsh.llm import deepseek_request
    from dsh.core.abort import AbortController
    original = deepseek_request.iter_chunks
    delivered = []
    controller = AbortController()
    monkeypatch.setattr(deepseek_request, 'AbortController', lambda: controller)

    async def delayed_delivery(stream):
        reader = original(stream)
        try:
            async for chunk in reader:
                if not delivered:
                    delivered.append(chunk['type'])
                    await asyncio.sleep(0.35)
                    assert not controller.signal.aborted
                yield chunk
        finally:
            await reader.aclose()

    monkeypatch.setattr(deepseek_request, 'iter_chunks', delayed_delivery)
    url, state = endpoint
    ctx, adapter, _ = await setup(tmp_path, url)
    adapter.config['streamIdleTimeoutMs'] = 250
    try:
        chunks = [chunk async for chunk in adapter.stream({'model': 'vision', 'messages': []})]
        assert delivered == ['block-start']
        assert chunks[-1]['type'] == 'finish'
        assert len(state['chats']) == 1
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_normalized_image_handle_uses_execution_world_mapping(tmp_path, endpoint):
    url, state = endpoint
    ctx, adapter, ref = await setup(tmp_path, url)
    calls = []
    def mapping(path):
        calls.append(path)
        return "/sandbox/read-only/red.png"
    ctx.set_service("fs", SimpleNamespace(processPathFromHostPath=mapping))
    try:
        _ = [chunk async for chunk in adapter.stream({"model": "vision", "messages": [
            {"role": "user", "content": [{"type": "image", "attachment": ref}]}]})]
        text = state["chats"][0]["messages"][0]["content"][0]["text"]
        assert "read-only" in text and '"/sandbox/read-only/red.png"' in text
        assert "Copy to a writable path ending in .png" in text
        assert calls == [ctx.get("attachments").image_host_path(ref)]
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_normalized_image_rejection_reports_exact_request_facts(tmp_path, endpoint):
    url, state = endpoint
    state["mode"] = "invalid-image"
    ctx, adapter, ref = await setup(tmp_path, url)
    try:
        with pytest.raises(LlmError, match="8-bit sRGB, 20x20") as caught:
            _ = [chunk async for chunk in adapter.stream({"model": "vision", "messages": [
                {"role": "user", "content": [{"type": "image", "attachment": ref}]}]})]
        assert caught.value.code == "INVALID_REQUEST"
        assert "message 1, image 1" in str(caught.value)
        assert len(state["uploads"]) == len(state["chats"]) == 1
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "fallback", "stale"])
async def test_image_request_wire_reuse_fallback_and_stale_retry(tmp_path, endpoint, mode):
    url, state = endpoint
    state["mode"] = mode
    ctx, adapter, ref = await setup(tmp_path, url)
    accepted, prepared = [], []
    def prepare(request):
        prepared.append(request["body"])
        return {"value": {"version": 1}, "accept": lambda: accepted.append(True)}
    ctx.get("deepseekLlmApiExtensions").register("test_extension", {"prepare": prepare})
    messages = [{"role": "user", "content": [{"type": "text", "text": "Inspect"}, {"type": "image", "attachment": ref}]},
                {"role": "user", "content": [{"type": "tool-result", "toolCallId": "tool-1", "content": [{"type": "image", "attachment": ref}]}]}]
    original = copy.deepcopy(messages)
    try:
        chunks = [chunk async for chunk in adapter.stream({"model": "vision", "messages": messages})]
        assert chunks[-1]["type"] == "finish" and accepted == [True]
        assert messages == original
        wire = state["chats"][-1]
        assert wire["test_extension"] == {"version": 1}
        kind = "image_url" if mode == "fallback" else "file"
        assert wire["messages"][0]["content"][-1]["type"] == kind
        assert wire["messages"][1]["role"] == "tool" and isinstance(wire["messages"][1]["content"], str)
        assert "request preview 20x20px" in wire["messages"][1]["content"]
        assert wire["messages"][2]["content"][0]["text"] == "Attached image(s) from tool result:"
        assert wire["messages"][2]["content"][1]["type"] == kind
        assert len(state["uploads"]) == (2 if mode == "stale" else 1)
        assert len(prepared) == (2 if mode == "stale" else 1)
        if mode != "fallback":
            uploads = len(state["uploads"])
            _ = [chunk async for chunk in adapter.stream({"model": "vision", "messages": messages})]
            assert len(state["uploads"]) == uploads
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["collision", "rejected", "accept-failed"])
async def test_extensions_only_accept_successful_requests_and_never_leak_errors(tmp_path, endpoint, case):
    url, state = endpoint
    ctx, adapter, _ = await setup(tmp_path, url)
    accepted = []
    def accept():
        accepted.append(True)
        if case == "accept-failed":
            raise ValueError("failed commit")
    ctx.get("deepseekLlmApiExtensions").register("model" if case == "collision" else "test_field",
        {"prepare": lambda _: {"value": "extension", "accept": accept}})
    if case == "rejected":
        state["mode"] = "reject"
    try:
        with pytest.raises(LlmError) as caught:
            _ = [chunk async for chunk in adapter.stream({"model": "vision", "messages": []})]
        assert caught.value.code == ("INVALID_REQUEST" if case == "rejected" else "REQUEST_EXTENSION")
        assert accepted == ([True] if case == "accept-failed" else [])
        assert len(state["chats"]) == (0 if case == "collision" else 1)
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_prepared_text_model_projects_images_without_altering_durable_messages(tmp_path, endpoint):
    from dsh.llm.llm_service import LLMService
    url, state = endpoint
    ctx, adapter, ref = await setup(tmp_path, url)
    llm = LLMService(ctx)
    llm.register_adapter(["deepseek-official"], adapter)
    messages = [{"role": "user", "content": [{"type": "image", "attachment": ref}]}]
    original = copy.deepcopy(messages)
    try:
        prepared = await llm.prepare_adapter_call("deepseek-official", "text-model")
        _ = [chunk async for chunk in prepared["stream"]({"model": "text-model", "messages": messages})]
        assert "image omitted because this model accepts text only" in state["chats"][0]["messages"][0]["content"]
        assert messages == original and not state["uploads"]
    finally:
        await adapter.close()
        await ctx.fiber.dispose()


def test_offload_quantized_oldest_prefix_accounts_for_nested_occurrences():
    from dsh.llm.image_content import offload, images
    mib = 1024 * 1024
    refs = [{"attachmentId": "sha256:" + str(i).zfill(64), "bytes": mib} for i in range(129)]
    messages = [{"role": "user", "content": [{"type": "tool-result", "toolCallId": "call", "content": [
        {"type": "image", "attachment": ref} for ref in refs]}]}]
    projected = offload(messages, 128 * mib, 600, 64 * mib, 20, lambda ref: ref["bytes"])
    retained = list(images(projected[0]["content"]))
    assert len(retained) == 64 and retained[0]["attachment"] is refs[65]
    assert len(list(images(messages[0]["content"]))) == 129
    inline = offload(messages, 10 * mib, 600, 5 * mib, 20, lambda ref: ref["bytes"], base64=True)
    assert len(list(images(inline[0]["content"]))) < 10
