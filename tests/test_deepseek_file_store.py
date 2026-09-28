import asyncio
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.llm.deepseek_file_store import DeepSeekFileStore
from dsh.llm.deepseek_files import DeepSeekFilesError
from dsh.llm.deepseek_upload_index import DeepSeekUploadIndex
from dsh.llm.llm_service import LlmError

CONNECTION = {"baseURL": "http://unused", "apiKey": "test-key"}
POLICY = {"expiresAfterSeconds": 604800, "refreshMarginSeconds": 3600, "quotaCleanupBatch": 1}
VERSION = {"attachment": {"attachmentId": "sha256:" + "a" * 64}, "variantId": "sha256:" + "b" * 64,
           "bytes": 3, "data": b"abc", "mediaType": "image/png"}


class Client:
    def __init__(self):
        self.uploads, self.deletes, self.pages = 0, [], []
        self.entered, self.release = threading.Event(), threading.Event()
        self.quota = False
        self.signals = []

    def upload(self, data, media_type, filename, expiry, signal=None):
        self.uploads += 1
        self.signals.append(signal)
        self.entered.set()
        while not self.release.wait(0.01):
            if signal.aborted:
                raise LlmError("upload cancelled", "ABORTED")
        if self.quota and self.uploads == 1:
            raise DeepSeekFilesError("quota", 400, "storage quota")
        return {"id": "file-" + str(self.uploads), "bytes": len(data), "createdAt": 0, "expiresAt": expiry}

    def list(self, after=None, **kwargs):
        self.pages.append(after)
        return {"data": [{"id": "user", "filename": "personal.png"}, {"id": "owned", "filename": "dsh-owned.png"}], "hasMore": False}

    def delete(self, file_id, signal=None):
        self.deletes.append(file_id)


async def entered(client):
    for _ in range(100):
        if client.entered.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("upload did not start")


@pytest.mark.asyncio
async def test_shared_upload_retains_independent_waits_and_reuses_durable_mapping(tmp_path):
    client = Client()
    index = DeepSeekUploadIndex(str(tmp_path / "files.json"))
    store = DeepSeekFileStore(index, now=lambda: 0, client_factory=lambda _: client)
    controller = AbortController()
    first = asyncio.create_task(store.ensure_uploaded(VERSION, CONNECTION, POLICY, controller.signal))
    second = asyncio.create_task(store.ensure_uploaded(VERSION, CONNECTION, POLICY))
    try:
        await entered(client)
        controller.abort()
        with pytest.raises(LlmError, match="cancelled"):
            await first
        assert not client.signals[0].aborted
        client.release.set()
        result = await second
        assert result["uploaded"] and client.uploads == 1
        reopened = DeepSeekFileStore(index, now=lambda: 0, client_factory=lambda _: client)
        assert not (await reopened.ensure_uploaded(VERSION, CONNECTION, POLICY))["uploaded"]
        assert client.uploads == 1
        assert await reopened.release(VERSION, CONNECTION, POLICY)
        assert client.deletes == ["file-1"]
    finally:
        client.release.set()
        await store.close()


@pytest.mark.asyncio
async def test_last_cancelled_waiter_stops_transport_and_teardown_drains(tmp_path):
    client = Client()
    store = DeepSeekFileStore(DeepSeekUploadIndex(str(tmp_path / "files.json")), client_factory=lambda _: client)
    pending = asyncio.create_task(store.ensure_uploaded(VERSION, CONNECTION, POLICY))
    await entered(client)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert client.signals[0].aborted
    await asyncio.wait_for(store.close(), 1)
    assert not store.inflight


@pytest.mark.asyncio
async def test_quota_cleanup_only_deletes_owned_files_and_retries_once(tmp_path):
    client = Client()
    client.quota = True
    client.release.set()
    store = DeepSeekFileStore(DeepSeekUploadIndex(str(tmp_path / "files.json")), now=lambda: 0, client_factory=lambda _: client)
    result = await store.ensure_uploaded(VERSION, CONNECTION, POLICY)
    assert result["record"]["fileId"] == "file-2"
    assert client.uploads == 2 and client.deletes == ["owned"] and client.pages == [None]
    await store.close()
