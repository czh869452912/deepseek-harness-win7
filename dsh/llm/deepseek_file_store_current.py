"""Messages file reuse, independently cancellable waiters and quota recovery."""
import asyncio
from functools import cmp_to_key
import time

from dsh.core.abort import AbortController
from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.json_text import stringify_json
from dsh.llm.deepseek_files_current import DeepSeekFilesClient, isFilesQuotaError
from dsh.llm.deepseek_model_info_current import messagesApiRoot
from dsh.llm.deepseek_upload_index_current import DeepSeekUploadIndex, deepSeekFileScope
from dsh.llm.llm_service import LlmError
from dsh.session.icu_collation import locale_compare

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def fileScope(connection):
    entries = sorted(connection['headers'].items(), key=cmp_to_key(lambda left, right: locale_compare(left[0], right[0])))
    return deepSeekFileScope(messagesApiRoot(connection['baseURL']), stringify_json([list(row) for row in entries]))


def _abort_reason(signal):
    if isinstance(signal.reason, BaseException): return signal.reason
    error = RuntimeError('DeepSeek file upload cancelled with a non-Error reason.')
    error.cause = signal.reason
    return error


def filename(version):
    extension = {'image/png': 'png', 'image/jpeg': 'jpeg', 'image/webp': 'webp', 'image/gif': 'gif'}[version['mediaType']]
    return 'dsh-'+version['attachment']['attachmentId'][7:23]+'-'+version['variantId'][7:15]+'.'+extension


class DeepSeekFileStore:
    def __init__(self, index=None, now=None, client_factory=None):
        self.index = index if index is not None else DeepSeekUploadIndex()
        self.now = now if now is not None else lambda: int(time.time()*1000)
        self.client_factory = client_factory or (lambda connection: DeepSeekFilesClient(connection['baseURL'], connection['headers']))
        self.inflight = {}

    def ensureUploaded(self, version, connection, policy, signal=None):
        if signal is not None: signal.throw_if_aborted()
        key = (fileScope(connection), version['variantId'])
        operation = self.inflight.get(key)
        if operation is not None and operation['controller'].signal.aborted:
            self.inflight.pop(key); operation = None
        if operation is None:
            operation = dict(controller=AbortController(), settled=False, waiters=0)
            operation['task'] = start_coroutine(self._owned_upload(version, connection, policy, operation['controller'].signal))
            self.inflight[key] = operation
            def finished(task, shared=operation):
                shared['settled'] = True
                if self.inflight.get(key) is shared: self.inflight.pop(key)
                if not task.cancelled(): task.exception()
            operation['task'].add_done_callback(finished)
        return self._wait(operation, signal)

    async def _owned_upload(self, version, connection, policy, signal):
        try: return await self._ensure_once(version, connection, policy, signal)
        except ThrownValueError as thrown:
            error = RuntimeError('DeepSeek file upload failed with a non-Error reason.')
            error.cause = thrown.value
            raise error from thrown

    def _wait(self, operation, signal):
        if signal is not None: signal.throw_if_aborted()
        operation['waiters'] += 1
        released = False
        waiter = asyncio.get_running_loop().create_future()
        def release(reason=None):
            nonlocal released
            if released: return
            released = True; operation['waiters'] -= 1
            if reason is not None and operation['waiters'] == 0 and not operation['settled']:
                operation['controller'].abort(reason)
        detach = lambda: None
        if signal is not None:
            def aborted(*_):
                reason = _abort_reason(signal); release(reason)
                detach()
                if not waiter.done(): waiter.set_exception(reason)
            detach = signal.add_listener('abort', aborted)
        def complete(task):
            detach(); release()
            if waiter.done(): return
            if task.cancelled(): waiter.cancel()
            else:
                error = task.exception()
                if error is not None: waiter.set_exception(error)
                else: waiter.set_result(task.result())
        operation['task'].add_done_callback(complete)
        def cancelled(future):
            if future.cancelled():
                detach(); release(RuntimeError('DeepSeek file upload wait cancelled.'))
        waiter.add_done_callback(cancelled)
        return waiter

    async def _ensure_once(self, version, connection, policy, signal):
        if version['bytes'] > MAX_IMAGE_BYTES:
            raise LlmError('DeepSeek image exceeds the 32 MiB per-image limit.', 'INVALID_REQUEST')
        scope = fileScope(connection); margin = policy['refreshMarginSeconds']*1000
        cached = await await_callback_result(self.index.get(scope, version['variantId'], self.now(), margin))
        if cached is not None: return dict(record=cached, uploaded=False)
        client = self.client_factory(connection)
        async def upload():
            remote = await await_callback_result(client.upload(data=version['data'], mediaType=version['mediaType'],
                filename=filename(version), expiresAfterSeconds=policy['expiresAfterSeconds'], signal=signal))
            if remote['bytes'] != len(version['data']):
                raise LlmError('DeepSeek Files API upload response does not match the submitted image.', 'INVALID_RESPONSE')
            return dict(scope=scope, attachmentId=version['attachment']['attachmentId'], variantId=version['variantId'],
                fileId=remote['id'], bytes=remote['bytes'], createdAt=remote['createdAt']*1000, expiresAt=remote['expiresAt']*1000)
        try: candidate = await upload()
        except Exception as error:
            if not isFilesQuotaError(error): raise
            deleted = await self.reclaimOldestOwned(connection, policy['quotaCleanupBatch'], signal)
            if deleted == 0: raise
            candidate = await upload()
        committed = await await_callback_result(self.index.commit(candidate, self.now(), margin))
        if not committed['accepted']:
            try: await await_callback_result(client.delete(candidate['fileId'], signal))
            except Exception: pass
        return dict(record=committed['record'], uploaded=committed['accepted'])

    async def invalidate(self, generations, connection):
        await await_callback_result(self.index.remove(fileScope(connection), generations))

    async def release(self, version, connection, policy, signal=None):
        scope = fileScope(connection)
        record = await await_callback_result(self.index.get(scope, version['variantId'], self.now(), policy['refreshMarginSeconds']*1000))
        if record is None: return False
        await await_callback_result(self.client_factory(connection).delete(record['fileId'], signal))
        await await_callback_result(self.index.remove(scope, [dict(variantId=version['variantId'], fileId=record['fileId'])]))
        return True

    async def reclaimOldestOwned(self, connection, count, signal=None):
        client = self.client_factory(connection); after = None; owned = []
        while True:
            page = await await_callback_result(client.list(after=after, limit=1000, signal=signal))
            owned.extend(dict(id=row['id'], createdAt=row['createdAt']) for row in page['data'] if row['filename'].startswith('dsh-'))
            owned.sort(key=lambda row: row['createdAt']); del owned[count:]
            if not page['hasMore'] or 'lastId' not in page or page['lastId'] == after: break
            after = page['lastId']
        for row in owned: await await_callback_result(client.delete(row['id'], signal))
        return len(owned)

    async def releaseAll(self, connection, signal=None):
        total = 0
        while True:
            deleted = await self.reclaimOldestOwned(connection, 1000, signal); total += deleted
            if deleted < 1000: break
        await await_callback_result(self.index.clear(fileScope(connection)))
        return total

    async def close(self):
        # Native plugin teardown owns and joins its HTTP readers.
        work = list(self.inflight.values())
        for operation in work: operation['controller'].abort(RuntimeError('DeepSeek file store disposed.'))
        if work: await asyncio.gather(*(asyncio.shield(operation['task']) for operation in work), return_exceptions=True)
