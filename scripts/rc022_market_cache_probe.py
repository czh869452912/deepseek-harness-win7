"""Paired market document cache lifetime and URL ownership observations."""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

URL = 'https://market.example/index.json'
OTHER = 'https://other.example/index.json'
URLS = [' HTTPS://Example.COM:443/a/../index.json?q=1 ', 'http://localhost:80/a', 'file:///index.json',
        'relative', 'https://u:p@example.com/', 'https://example.com/#', 'https://例子.测试/市场',
        'https://127.1/index.json', 'https://[::1]:443/a', 'https:\\example.com\\a', '\u3000https://example.com/a\u3000']


async def observe():
    from dsh.boot.market_document_022 import MarketDocumentCache, normalize_index_url
    rows = []
    def failure(error):
        return dict(code=getattr(error, 'code', None), message=str(error), details=getattr(error, 'details', None))
    for url in URLS:
        try: rows.append(dict(step='url', input=url, value=normalize_index_url(url)))
        except Exception as error: rows.append(dict(step='url', input=url, error=failure(error)))
    urls = [URL]; now = [1000]; calls = []; gates = []
    async def fetch(url, signal):
        calls.append(url); gate = asyncio.get_running_loop().create_future(); gates.append(gate)
        def abort(_):
            if not gate.done(): gate.set_exception(signal.reason)
        remove = signal.add_listener('abort', abort)
        try: return await gate
        finally: remove()
    cache = MarketDocumentCache(lambda: urls, fetch, 100, lambda: now[0])
    async def pump(): await asyncio.sleep(0); await asyncio.sleep(0)
    async def read(title, refresh=False, pin=None):
        task = asyncio.create_task(cache.document(URL, refresh, pin)); await pump()
        if not task.done() and gates and not gates[-1].done(): gates[-1].set_result(dict(title=title, plugins=[]))
        return await task
    def snapshot(step, **extra):
        rows.append(dict(step=step, calls=len(calls), indexes=cache.list_indexes(), **extra))
    try:
        snapshot('initial')
        first = asyncio.create_task(cache.document(URL)); second = asyncio.create_task(cache.document(URL)); await pump()
        rows.append(dict(step='sharing', calls=len(calls), pending=len(cache.pending)))
        gates[-1].set_result(dict(title='A', plugins=[])); a, b = await asyncio.gather(first, second)
        snapshot('shared-result', same=a is b, fetchedAt=a['fetchedAt'])
        value = await read('unused'); snapshot('cached', fetchedAt=value['fetchedAt'])
        value = await read('B', True); snapshot('refresh', fetchedAt=value['fetchedAt'])
        now[0] = 1100
        value = await read('unused', pin=value['fetchedAt']); snapshot('pinned-expired', fetchedAt=value['fetchedAt'])
        value = await read('C'); snapshot('expired', fetchedAt=value['fetchedAt'])
        task = asyncio.create_task(cache.document(URL, True)); await pump(); gates[-1].set_exception(RuntimeError('offline'))
        try: await task
        except Exception as error: snapshot('failed-keeps-title', error=failure(error))
        value = await read('D', True); snapshot('success-clears-error', fetchedAt=value['fetchedAt'])
        for target in [OTHER, 'https://EXAMPLE.com:443/index.json', 'https://u:p@example.com/']:
            if target != OTHER: urls.append(target)
            try: await cache.document(target)
            except Exception as error: rows.append(dict(step='refusal', error=failure(error)))
        urls[:] = [URL, URL, 'https://EXAMPLE.com:443/index.json', 'https://u:p@example.com/']; snapshot('configured-refusals')
        for replacement in [[URL, ' https://other.example:443/index.json '],
                            ['https://EXAMPLE.com:443/index.json', 'https://example.com/index.json'],
                            ['https://u:p@example.com/', URL], ['relative']]:
            try: rows.append(dict(step='replace', value=cache.normalize_replacement(replacement)))
            except Exception as error: rows.append(dict(step='replace', error=failure(error)))
        urls[:] = []; cache.volatile_update(); snapshot('removed')
        urls[:] = [URL]; task = asyncio.create_task(cache.document(URL)); await pump()
        urls[:] = []; gates[-1].set_result(dict(title='Late', plugins=[])); await task
        urls[:] = [URL]; snapshot('late-success-not-retained')
        task = asyncio.create_task(cache.document(URL)); await pump(); urls[:] = []; gates[-1].set_exception(RuntimeError('late failure'))
        try: await task
        except RuntimeError: pass
        urls[:] = [URL]; snapshot('late-failure-not-retained')
        task = asyncio.create_task(cache.document(URL)); await pump(); task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        snapshot('caller-cancel-keeps-shared', pending=len(cache.pending))
        second = asyncio.create_task(cache.document(URL)); await pump(); gates[-1].set_result(dict(title='Still shared', plugins=[])); await second
        snapshot('other-caller-completes')
        task = asyncio.create_task(cache.document(URL, True)); await pump(); await cache.dispose()
        try: await task
        except Exception as error: rows.append(dict(step='dispose', error=failure(error), pending=len(cache.pending), aborted=cache.lifetime.signal.aborted))
    finally: await cache.dispose()
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_cache.mts', scope='Canonical index URLs, configured-source refusals and replacement, shared fetch ownership, TTL/pinned documents, monotonic fetch identity, late success/failure removal and abort disposal; validated fetch collaborator, no HTTP/detail/annotation claims.',
        extra_inputs=[ROOT/'dsh/boot/market_document_022.py', ROOT/'scripts/rc022_market_cache_probe.py', ROOT/'dsh/boot/market-index/manifest.json'])
