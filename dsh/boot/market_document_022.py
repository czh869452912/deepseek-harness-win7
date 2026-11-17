"""Market document ownership, shared fetches and pinned-page cache semantics.

The provider supplies the validated index fetch and a live configured-URL getter.
HTTP/body parsing, listing annotation and Remote declarations are separate layers.
"""
import asyncio
from functools import lru_cache
import time

from dsh.boot.market_index_022 import observe_market_operations
from dsh.core.abort import AbortController
from dsh.typert.remote import RemoteError


@lru_cache(maxsize=1024)
def _url_facts(text):
    row = observe_market_operations([dict(kind='url', text=text)])[0]
    if row['ok']:
        return row['canonical'], row['value'], None
    error = row['error']
    return error['canonical'], None, error


def normalize_index_url(text):
    _, value, error = _url_facts(text)
    if error is not None:
        raise RemoteError(error['code'], error['message'], dict(error['details']))
    return value


class MarketDocumentCache:
    def __init__(self, indexes, fetch_index, ttl_ms=600000, clock=None):
        self.indexes, self.fetch_index, self.ttl_ms = indexes, fetch_index, ttl_ms
        self.clock = clock or (lambda: int(time.time()*1000))
        self.cache, self.pending, self.errors = {}, {}, {}
        self.lifetime = AbortController()

    def sources(self):
        seen, rows = set(), []
        for url in self.indexes():
            if url in seen:
                continue
            seen.add(url)
            _, normalized, error = _url_facts(url)
            row = dict(url=url)
            if error is not None:
                row['error'] = error['message']
            elif normalized != url:
                row['error'] = 'Index URL is not in canonical form; use ' + normalized
            rows.append(row)
        return rows

    def list_indexes(self):
        rows = []
        for source in self.sources():
            url = source['url']; row = dict(url=url)
            if url in self.cache:
                index = self.cache[url]['document']['index']
                row['title'] = index['title']
                if 'description' in index:
                    row['description'] = index['description']
            error = source.get('error', self.errors.get(url))
            if error is not None:
                row['error'] = error
            rows.append(row)
        return rows

    def normalize_replacement(self, urls):
        configured = set(self.indexes())
        normalized = [url if url in configured else normalize_index_url(url) for url in urls]
        seen = set()
        for url in normalized:
            key = _url_facts(url)[0]
            if key in seen:
                raise RemoteError('plugin-market/invalid-index-url', 'Index source listed twice: '+url,
                                  dict(url=url, reason='duplicate'))
            seen.add(key)
        return normalized

    def volatile_update(self):
        configured = {source['url'] for source in self.sources() if 'error' not in source}
        for url in set(self.cache) | set(self.errors):
            if url not in configured:
                self.cache.pop(url, None)
                self.errors.pop(url, None)

    def configured(self, url):
        return any(source['url'] == url and 'error' not in source for source in self.sources())

    async def document(self, url, refresh=False, fetched_at=None):
        source = next((source for source in self.sources() if source['url'] == url), None)
        if source is None:
            raise RemoteError('plugin-market/unknown-index', 'Not a configured index source: '+url, dict(url=url))
        if 'error' in source:
            raise RemoteError('plugin-market/invalid-index-url', source['error'], dict(url=url, reason='configured'))
        cached = self.cache.get(url)
        usable = cached is not None and (cached['expiresAt'] > self.clock() or cached['document']['fetchedAt'] == fetched_at)
        if refresh is not True and usable:
            return cached['document']
        return await asyncio.shield(self.fetch_shared(url))

    def fetch_shared(self, url):
        if url not in self.pending:
            async def fetch():
                try:
                    index = await self.fetch_index(url, self.lifetime.signal)
                    previous = self.cache.get(url)
                    fetched_at = max(self.clock(), (previous['document']['fetchedAt'] if previous else 0)+1)
                    document = dict(index=index, fetchedAt=fetched_at)
                    if self.configured(url):
                        self.cache[url] = dict(document=document, expiresAt=self.clock()+self.ttl_ms)
                        self.errors.pop(url, None)
                    return document
                except Exception as error:
                    if self.configured(url):
                        self.errors[url] = str(error)
                    raise
                finally:
                    self.pending.pop(url, None)
            task = asyncio.create_task(fetch())
            task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            self.pending[url] = task
        return self.pending[url]

    async def dispose(self):
        self.lifetime.abort(RuntimeError('Plugin market disposed'))
        await asyncio.gather(*list(self.pending.values()), return_exceptions=True)
