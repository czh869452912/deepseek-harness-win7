import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.llm.deepseek_files import DeepSeekFilesClient, DeepSeekFilesError, is_files_quota_error
from dsh.llm.llm_service import LlmError
from dsh.llm.deepseek_upload_index import DeepSeekUploadIndex, file_scope


@pytest.fixture
def files_server():
    state = {"requests": [], "status": 200, "reply": {
        "id": "file-one", "object": "file", "bytes": 3, "created_at": 1700000000,
        "filename": "image.png", "purpose": "user_data", "expires_at": 1700604800}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def handle_request(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["requests"].append((self.command, self.path, dict(self.headers), data))
            body = json.dumps(state["reply"]).encode("utf-8")
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST = do_DELETE = handle_request
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield DeepSeekFilesClient("http://127.0.0.1:{}/".format(server.server_port), "test-only"), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_multipart_upload_and_escaped_retrieve_delete_and_pagination(files_server):
    client, state = files_server
    assert client.upload(b"abc", "image/png", "image.png", 604800)["expiresAt"] == 1700604800
    method, path, headers, body = state["requests"][-1]
    assert (method, path, headers["Authorization"]) == ("POST", "/files", "Bearer test-only")
    from dsh.llm.attribution import attribution_headers
    assert headers["User-Agent"] == attribution_headers()["User-Agent"]
    mime = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + body)
    fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in mime.iter_parts()}
    assert fields == {"purpose": b"user_data", "expires_after[anchor]": b"created_at", "expires_after[seconds]": b"604800", "file": b"abc"}
    client.retrieve("id/with?special")
    assert state["requests"][-1][1] == "/files/id%2Fwith%3Fspecial"
    state["reply"] = {"object": "list", "data": [state["reply"]], "has_more": True, "last_id": "file-one"}
    assert client.list(after="a/b", limit=2, order="asc")["hasMore"]
    assert "after=a%2Fb" in state["requests"][-1][1]
    state["reply"] = {"object": "file", "id": "file-one", "deleted": True}
    assert client.delete("file-one") is None
    assert state["requests"][-1][0] == "DELETE"


@pytest.mark.parametrize("status,code", [(401, "AUTH"), (403, "AUTH"), (429, "RATE_LIMIT"), (503, "SERVER"), (400, "FILES_API")])
def test_files_errors_preserve_status_and_quota_classification(files_server, status, code):
    client, state = files_server
    state.update(status=status, reply={"error": {"message": "storage quota exceeded", "code": "quota"}})
    with pytest.raises(DeepSeekFilesError) as caught:
        client.retrieve("file-one")
    assert caught.value.code == code and caught.value.status == status
    assert is_files_quota_error(caught.value)


@pytest.mark.parametrize("field,value", [("bytes", True), ("created_at", -1), ("id", ""), ("purpose", "assistants"), ("expires_at", None)])
def test_invalid_upload_responses_rejected(files_server, field, value):
    client, state = files_server
    state["reply"][field] = value
    with pytest.raises(LlmError) as caught:
        client.upload(b"abc", "image/png", "image.png", 3600)
    assert caught.value.code == "INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_upload_index_generation_safe_namespace_recovery_and_commit_race(tmp_path):
    import asyncio
    path = tmp_path / "files.json"
    index, other = DeepSeekUploadIndex(str(path)), DeepSeekUploadIndex(str(path))
    scope = file_scope("https://example.invalid/", "secret")
    candidate = dict(scope=scope, attachmentId="sha256:" + "a" * 64, variantId="sha256:" + "b" * 64,
                     fileId="first", bytes=3, createdAt=0, expiresAt=10000)
    results = await asyncio.gather(index.commit(candidate, 0, 100), other.commit(dict(candidate, fileId="second"), 0, 100))
    assert [row["accepted"] for row in results] == [True, False]
    assert results[1]["record"]["fileId"] == "first"
    assert "secret" not in path.read_text(encoding="utf-8")
    assert scope == file_scope("https://example.invalid", "secret")
    assert await index.get(file_scope("https://example.invalid", "other"), candidate["variantId"], 0, 100) is None
    await other.commit(dict(candidate, fileId="successor", expiresAt=20000), 10000, 100)
    await index.remove(scope, candidate["variantId"], "first")
    assert (await other.get(scope, candidate["variantId"], 10000, 100))["fileId"] == "successor"
    path.write_text('{"formatVersion":3,"records":[false]}', encoding="utf-8")
    assert await index.get(scope, candidate["variantId"], 0, 100) is None
    await index.commit(candidate, 0, 100)
    await index.clear(scope)
    assert json.loads(path.read_text(encoding="utf-8"))["records"] == []
