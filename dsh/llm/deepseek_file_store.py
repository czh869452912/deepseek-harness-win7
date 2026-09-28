"""Shared, independently cancellable image uploads and bounded quota recovery."""
import asyncio
import functools
import time

from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted
from dsh.llm.deepseek_files import DeepSeekFilesClient, is_files_quota_error
from dsh.llm.deepseek_upload_index import DeepSeekUploadIndex, file_scope
from dsh.llm.llm_service import LlmError


def throw_if_aborted(signal):
    if aborted(signal):
        raise LlmError("DeepSeek file upload cancelled", "ABORTED")


class DeepSeekFileStore:
    def __init__(self, index=None, now=None, client_factory=None):
        self.index = index or DeepSeekUploadIndex()
        self.now = now or (lambda: int(time.time() * 1000))
        self.client_factory = client_factory or (lambda connection: DeepSeekFilesClient(
            connection["baseURL"], connection["apiKey"], connection.get("filesApiTimeoutMs", 60000)))
        self.inflight = {}

    async def _call(self, connection, method, *args, **kwargs):
        operation = functools.partial(getattr(self.client_factory(connection), method), *args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(None, operation)

    async def ensure_uploaded(self, version, connection, policy, signal=None):
        throw_if_aborted(signal)
        key = (file_scope(connection["baseURL"], connection["apiKey"]), version["variantId"])
        shared = self.inflight.get(key)
        if shared is None or shared["controller"].signal.aborted:
            controller = AbortController()
            task = asyncio.create_task(self._ensure_once(version, connection, policy, controller.signal))
            shared = {"controller": controller, "task": task, "waiters": 0}
            self.inflight[key] = shared
            def finish(completed, entry=shared):
                if self.inflight.get(key) is entry:
                    self.inflight.pop(key, None)
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(finish)
        shared["waiters"] += 1
        cancelled = False
        try:
            while not shared["task"].done():
                throw_if_aborted(signal)
                await asyncio.wait({shared["task"]}, timeout=0.02)
            throw_if_aborted(signal)
            return shared["task"].result()
        except (asyncio.CancelledError, LlmError):
            cancelled = True
            raise
        finally:
            shared["waiters"] -= 1
            if cancelled and shared["waiters"] == 0 and not shared["task"].done():
                shared["controller"].abort("last upload waiter cancelled")

    async def _ensure_once(self, version, connection, policy, signal):
        if version["bytes"] > 32 * 1024 * 1024:
            raise LlmError("DeepSeek chat image exceeds the 32 MiB per-image limit.", "INVALID_REQUEST")
        scope = file_scope(connection["baseURL"], connection["apiKey"])
        margin = policy["refreshMarginSeconds"] * 1000
        cached = await self.index.get(scope, version["variantId"], self.now(), margin)
        if cached is not None:
            return {"record": cached, "uploaded": False}
        suffix = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "image/gif": "gif"}[version["mediaType"]]
        filename = "dsh-{}-{}.{}".format(version["attachment"]["attachmentId"][7:23], version["variantId"][7:15], suffix)
        async def upload():
            remote = await self._call(connection, "upload", version["data"], version["mediaType"], filename,
                                      policy["expiresAfterSeconds"], signal=signal)
            if remote["bytes"] != len(version["data"]):
                raise LlmError("DeepSeek Files API upload response does not match submitted image.", "INVALID_RESPONSE")
            return dict(scope=scope, attachmentId=version["attachment"]["attachmentId"], variantId=version["variantId"],
                        fileId=remote["id"], bytes=remote["bytes"], createdAt=remote["createdAt"] * 1000,
                        expiresAt=remote["expiresAt"] * 1000)
        try:
            candidate = await upload()
        except Exception as error:
            if not is_files_quota_error(error):
                raise
            if not await self.reclaim_oldest_owned(connection, policy["quotaCleanupBatch"], signal):
                raise
            candidate = await upload()
        committed = await self.index.commit(candidate, self.now(), margin)
        if not committed["accepted"]:
            try:
                await self._call(connection, "delete", candidate["fileId"], signal=signal)
            except Exception:
                pass  # The durable winner remains usable; quota recovery owns duplicate cleanup.
        return {"record": committed["record"], "uploaded": committed["accepted"]}

    async def invalidate(self, version, file_id, connection):
        await self.index.remove(file_scope(connection["baseURL"], connection["apiKey"]), version["variantId"], file_id)

    async def release(self, version, connection, policy, signal=None):
        scope = file_scope(connection["baseURL"], connection["apiKey"])
        record = await self.index.get(scope, version["variantId"], self.now(), policy["refreshMarginSeconds"] * 1000)
        if record is None:
            return False
        await self._call(connection, "delete", record["fileId"], signal=signal)
        await self.index.remove(scope, version["variantId"], record["fileId"])
        return True

    async def reclaim_oldest_owned(self, connection, count, signal=None):
        owned, after = [], None
        while len(owned) < count:
            throw_if_aborted(signal)
            page = await self._call(connection, "list", after=after, limit=1000, order="asc", signal=signal)
            for row in page["data"]:
                if row["filename"].startswith("dsh-"):
                    owned.append(row["id"])
                    if len(owned) == count:
                        break
            if not page["hasMore"] or not page.get("lastId") or page["lastId"] == after:
                break
            after = page["lastId"]
        for file_id in owned:
            throw_if_aborted(signal)
            await self._call(connection, "delete", file_id, signal=signal)
        return len(owned)

    async def release_all(self, connection, signal=None):
        total = 0
        while True:
            deleted = await self.reclaim_oldest_owned(connection, 1000, signal)
            total += deleted
            if deleted < 1000:
                break
        await self.index.clear(file_scope(connection["baseURL"], connection["apiKey"]))
        return total

    async def close(self):
        work = list(self.inflight.values())
        for shared in work:
            shared["controller"].abort("provider disposed")
        if work:
            await asyncio.gather(*(shared["task"] for shared in work), return_exceptions=True)
