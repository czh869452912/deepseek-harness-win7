import asyncio

import pytest

from dsh.boot.market_document_022 import MarketDocumentCache, normalize_index_url
from dsh.typert.remote import RemoteError
from scripts.rc022_market_cache_probe import observe, URL


@pytest.mark.asyncio
async def test_cache_observations_cover_lifetime_and_pinned_pages():
    rows = await observe()
    by = {row['step']: row for row in rows}
    assert by['sharing']['calls'] == by['shared-result']['calls'] == 1
    assert by['shared-result']['same']
    assert by['refresh']['fetchedAt'] == 1001
    assert by['pinned-expired']['fetchedAt'] == 1001
    assert by['expired']['fetchedAt'] == 1100
    assert by['failed-keeps-title']['indexes'][0]['title'] == 'C'
    assert 'error' not in by['success-clears-error']['indexes'][0]
    assert by['late-success-not-retained']['indexes'] == [dict(url=URL)]
    assert by['late-failure-not-retained']['indexes'] == [dict(url=URL)]
    assert by['caller-cancel-keeps-shared']['pending'] == 1
    assert by['dispose']['aborted'] and by['dispose']['pending'] == 0


@pytest.mark.parametrize('url,reason', [('relative', 'not-absolute'), ('file:///a', 'scheme'),
    ('https://u:p@example.com/', 'credentials-or-fragment'), ('https://example.com/#', 'credentials-or-fragment')])
def test_normalizer_preserves_remote_failure(url, reason):
    with pytest.raises(RemoteError) as caught:
        normalize_index_url(url)
    assert caught.value.code == 'plugin-market/invalid-index-url'
    assert caught.value.details == dict(url=url, reason=reason)


@pytest.mark.asyncio
async def test_failed_shared_fetch_is_released_before_retry():
    calls = []
    async def fetch(url, signal):
        calls.append(url)
        if len(calls) == 1:
            raise RemoteError('plugin-market/fetch-failed', 'offline', dict(url=url, reason='offline'))
        return dict(title='Recovered', plugins=[])
    cache = MarketDocumentCache(lambda: [URL], fetch, clock=lambda: 0)
    try:
        with pytest.raises(RemoteError): await cache.document(URL)
        assert not cache.pending
        assert cache.list_indexes() == [dict(url=URL, error='offline')]
        assert (await cache.document(URL))['fetchedAt'] == 1
        assert cache.list_indexes() == [dict(url=URL, title='Recovered')]
        assert calls == [URL, URL]
    finally: await cache.dispose()


@pytest.mark.asyncio
async def test_expired_pin_does_not_recover_replaced_document():
    count = 0; now = [100]
    async def fetch(url, signal):
        nonlocal count
        count += 1
        return dict(title=str(count), plugins=[])
    cache = MarketDocumentCache(lambda: [URL], fetch, ttl_ms=10, clock=lambda: now[0])
    try:
        original = await cache.document(URL)
        replaced = await cache.document(URL, True)
        now[0] = 200
        latest = await cache.document(URL, fetched_at=original['fetchedAt'])
        assert latest['index']['title'] == '3'
        assert latest is not original and latest is not replaced
    finally: await cache.dispose()


@pytest.mark.asyncio
async def test_disposal_waits_for_fetch_cleanup_and_aborts_reason():
    entered, release = asyncio.Event(), asyncio.Event()
    async def fetch(url, signal):
        entered.set()
        await signal.wait_aborted()
        await release.wait()
        signal.throwIfAborted()
    cache = MarketDocumentCache(lambda: [URL], fetch)
    reader = asyncio.create_task(cache.document(URL)); await entered.wait()
    closing = asyncio.create_task(cache.dispose()); await asyncio.sleep(0)
    assert not closing.done()
    assert str(cache.lifetime.signal.reason) == 'Plugin market disposed'
    release.set(); await closing
    with pytest.raises(RuntimeError, match='Plugin market disposed'): await reader
    assert not cache.pending


@pytest.mark.asyncio
async def test_invalid_configured_source_never_starts_fetch():
    async def fetch(*_): raise AssertionError('must not fetch')
    urls = ['https://EXAMPLE.com:443/index.json', 'https://u:p@example.com/', 'relative']
    cache = MarketDocumentCache(lambda: urls, fetch)
    try:
        for url in urls:
            with pytest.raises(RemoteError) as caught: await cache.document(url)
            assert caught.value.code == 'plugin-market/invalid-index-url'
            assert caught.value.details == dict(url=url, reason='configured')
        with pytest.raises(RemoteError) as caught: await cache.document(URL)
        assert caught.value.code == 'plugin-market/unknown-index'
        assert not cache.pending
    finally: await cache.dispose()


def test_replacement_preserves_kept_invalid_but_rejects_new_duplicate():
    urls = ['relative', 'https://EXAMPLE.com:443/index.json']
    cache = MarketDocumentCache(lambda: urls, None)
    assert cache.normalize_replacement(['relative', ' https://other.example:443/a ']) == ['relative', 'https://other.example/a']
    with pytest.raises(RemoteError) as caught:
        cache.normalize_replacement([urls[1], 'https://example.com/index.json'])
    assert caught.value.details == dict(url='https://example.com/index.json', reason='duplicate')
