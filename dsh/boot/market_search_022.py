"""One owned Win7 worker reuses each live document's pinned MarketSearch."""
import asyncio
import json
import os
import subprocess

from dsh.boot.market_index_022 import RESOURCE_ROOT, market_bootstrap
from dsh.javascript.runtime import JavaScriptRuntimeError, JavaScriptWorker, verify_resources, worker_environment


def document_key(url, document):
    return json.dumps([url, document['fetchedAt']], separators=(',', ':'))


def _consume(task):
    if not task.cancelled():
        task.exception()


class MarketSearchWorker:
    def __init__(self, signal, timeout=30):
        signal.throwIfAborted()
        self.signal, self.timeout = signal, timeout
        self.worker, self.starting, self.closing = None, None, None
        self.closed, self.sequence = False, 0
        self.live, self.known, self.active = set(), set(), {}
        self.pending, self.jobs = {}, set()
        self.lock = asyncio.Lock()
        self.remove_abort = signal.add_listener('abort', lambda _: self.dispose())

    def _own(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.jobs.add(task)
        task.add_done_callback(self.jobs.discard)
        task.add_done_callback(_consume)
        return task

    async def _open(self):
        # market_bootstrap verifies every resource, including search-driver.js.
        bootstrap = market_bootstrap()+'\n'+(RESOURCE_ROOT/'search-driver.js').read_text(encoding='utf-8')
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(str(verify_resources()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=worker_environment(), limit=2147483647,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        process = None
        try:
            process = await asyncio.shield(spawn)
            self.worker = JavaScriptWorker(process, self._observe, 1000)
            await self.worker.send(dict(body='return null', name='market-search', timeoutMs=10000, bootstrap=bootstrap))
            await asyncio.shield(self.worker.ready)
            await self.worker.send(dict(type='go'))
            self._own(self._watch())
            return self.worker
        except BaseException:
            async def cleanup():
                owned = process if process is not None else await spawn
                if self.worker is not None:
                    await self.worker.terminate()
                else:
                    if owned.returncode is None: owned.kill()
                    await owned.communicate()
            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try: await asyncio.shield(cleanup_task)
                except asyncio.CancelledError: pass
            cleanup_task.result()
            raise

    def _observe(self, message):
        if message.get('type') != 'market-result' or message.get('id') not in self.pending:
            raise JavaScriptRuntimeError('Market search worker returned an unexpected result')
        future = self.pending[message['id']]
        if future.done():
            raise JavaScriptRuntimeError('Market search worker repeated a result')
        if 'error' in message:
            future.set_exception(ValueError(message['error']['message']))
        elif type(message.get('names')) is list and all(type(name) is str for name in message['names']):
            future.set_result(message['names'])
        else:
            raise JavaScriptRuntimeError('Market search worker returned invalid names')

    async def _watch(self):
        await asyncio.shield(self.worker.closed)
        error = self.worker.failure or JavaScriptRuntimeError('Market search worker closed')
        for future in list(self.pending.values()):
            if not future.done(): future.set_exception(error)
        self.dispose()

    def _keys(self):
        return self.live | set(self.active)

    async def _prune(self):
        async with self.lock:
            if self.worker is None or self.closed: return
            keys = self._keys()
            self.known.intersection_update(keys)
            await self.worker.send(dict(type='prune', keys=sorted(keys)))

    def retain(self, documents):
        self.live = {document_key(url, row['document']) for url, row in documents.items()}
        if self.worker is not None and not self.closed:
            self._own(self._prune())

    async def _query(self, url, document, selection):
        key = document_key(url, document)
        self.active[key] = self.active.get(key, 0)+1
        identity = None
        try:
            if self.starting is None:
                self.starting = asyncio.create_task(self._open())
                self.starting.add_done_callback(_consume)
            worker = await asyncio.shield(self.starting)
            async with self.lock:
                self.signal.throwIfAborted()
                if self.closed: raise JavaScriptRuntimeError('Market search worker disposed')
                self.sequence += 1
                identity = self.sequence
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_consume)
                self.pending[identity] = future
                keys = self._keys()
                self.known.intersection_update(keys)
                request = dict(type='search', id=identity, key=key, keys=sorted(keys), url=url, selection=selection)
                if key not in self.known:
                    request['index'] = document['index']
                await worker.send(request)
                self.known.add(key)
            return await asyncio.shield(future)
        finally:
            if identity is not None: self.pending.pop(identity, None)
            self.active[key] -= 1
            if not self.active[key]: self.active.pop(key)
            if self.worker is not None and not self.closed:
                self._own(self._prune())

    async def select(self, url, document, selection):
        self.signal.throwIfAborted()
        if self.closed: raise JavaScriptRuntimeError('Market search worker disposed')
        # A departing caller does not cancel other readers or the shared build.
        task = self._own(self._query(url, document, selection))
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.timeout)
        except asyncio.TimeoutError:
            await asyncio.shield(self.dispose())
            raise JavaScriptRuntimeError('Market search worker exceeded its operation deadline')
        except asyncio.CancelledError:
            self.signal.throwIfAborted()
            raise
        except Exception:
            self.signal.throwIfAborted()
            raise

    def dispose(self):
        if self.closing is None:
            self.closed = True
            self.remove_abort()
            self.closing = asyncio.create_task(self._dispose())
            self.closing.add_done_callback(_consume)
        return self.closing

    async def _dispose(self):
        if self.starting is not None and not self.starting.done():
            self.starting.cancel()
            await asyncio.gather(self.starting, return_exceptions=True)
        if self.worker is not None:
            await self.worker.terminate()
        await asyncio.gather(*list(self.jobs), return_exceptions=True)
        self.live.clear(); self.known.clear()
