"""Host registry selection with shared probes and owned HTTP response cleanup."""
import asyncio
import threading
import time
from types import SimpleNamespace

from dsh.cordis.schema import Schema
from dsh.core.abort import AbortController
from dsh.llm.http_stream import open_stream
from dsh.typert.remote import Remote, TypertRemoteService


REGISTRIES = ('https://registry.npmjs.org/', 'https://registry.npmmirror.com/')


async def fetch_ping(endpoint, signal, timeout_ms, redirect='error'):
    """Win7 Fetch adaptation: expose headers, close without reading the body, join owner.

    The existing owned HTTP transport applies the process proxy policy, rejects
    redirects and interrupts socket waits on abort. Its bounded DNS worker owns
    no socket; Python 3.8 has no cancellable getaddrinfo API.
    """
    loop = asyncio.get_running_loop()
    response = loop.create_future()
    release = threading.Event()
    operation = AbortController()
    detach = signal.add_listener('abort', lambda reason: operation.abort(reason))

    def settle(value=None, error=None):
        if not response.done():
            if error is not None:
                response.set_exception(error)
            else:
                response.set_result(value)

    def request():
        try:
            with open_stream(endpoint, operation.signal, idle_timeout_ms=timeout_ms,
                             redirect_policy=redirect, raise_http_errors=False) as (raw, _chunks):
                loop.call_soon_threadsafe(settle, raw.status)
                release.wait()
        except Exception as error:
            loop.call_soon_threadsafe(settle, None, error)

    worker = loop.run_in_executor(None, request)
    try:
        status = await asyncio.shield(response)
    except BaseException:
        operation.abort()
        release.set()
        await asyncio.shield(worker)
        detach()
        # Retrieve an exception if the caller was cancelled before headers.
        if response.done() and not response.cancelled():
            response.exception()
        raise

    async def cancel():
        operation.abort()
        release.set()
        try:
            await asyncio.shield(worker)
        finally:
            detach()

    return SimpleNamespace(ok=200 <= status < 300, status=status,
                           body=SimpleNamespace(cancel=cancel))


class CurrentPluginRegistryProbe(TypertRemoteService):
    Config = Schema.object(dict(
        registryProbeEnabled=Schema.boolean().default(True),
        registryProbeTimeoutMs=Schema.natural().min(1).max(2147483647).default(1500),
        registryProbeCacheTtlMs=Schema.natural().default(300000)))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'pluginRegistryProbe')
        self.config = dict(registryProbeEnabled=True, registryProbeTimeoutMs=1500,
                           registryProbeCacheTtlMs=300000)
        self.config.update(config or {})
        self.lifetime = AbortController()
        self.pending = None
        self.cached = None
        self._now = lambda: time.time() * 1000
        self._fetch = fetch_ping

        def close():
            self.lifetime.abort()
            async def drain():
                if self.pending is not None:
                    await asyncio.shield(self.pending)
            return drain()
        ctx.effect(lambda: close)

    @Remote('fastest')
    async def fastest(self):
        self.lifetime.signal.throwIfAborted()
        if not self.config['registryProbeEnabled']:
            return None
        if self.cached is not None and self.cached['expiresAt'] > self._now():
            return self.cached['registry']
        if self.pending is None:
            async def run():
                try:
                    return await self._probe()
                finally:
                    self.pending = None
            self.pending = asyncio.create_task(run())
        # A cancelled Python waiter must not cancel another Client's probe.
        return await asyncio.shield(self.pending)

    async def _probe(self):
        finished = AbortController()
        detach = self.lifetime.signal.add_listener('abort', lambda reason: finished.abort(reason))
        timer = asyncio.get_running_loop().call_later(
            self.config['registryProbeTimeoutMs'] / 1000, finished.abort)
        requests = []
        registry = None
        try:
            async def request(base):
                response = await self._fetch(base + '-/ping', finished.signal,
                                             self.config['registryProbeTimeoutMs'], redirect='error')
                return base, response
            requests = [asyncio.create_task(request(base)) for base in REGISTRIES]
            # Queue completion order, rather than iterating an unordered done set.
            arrivals = asyncio.Queue()
            for task in requests:
                task.add_done_callback(arrivals.put_nowait)
            for _ in requests:
                task = await arrivals.get()
                try:
                    base, response = task.result()
                    if response.ok:
                        registry = base
                        break
                except Exception:
                    pass
        finally:
            finished.abort()
            responses = await asyncio.gather(*requests, return_exceptions=True)
            async def discard(result):
                if isinstance(result, BaseException):
                    return
                body = getattr(result[1], 'body', None)
                if body is not None:
                    await body.cancel()
            await asyncio.gather(*(discard(result) for result in responses), return_exceptions=True)
            timer.cancel()
            detach()
        if not self.lifetime.signal.aborted:
            self.cached = dict(registry=registry, expiresAt=self._now() + self.config['registryProbeCacheTtlMs'])
        return registry
