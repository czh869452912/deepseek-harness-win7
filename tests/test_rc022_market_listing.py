import asyncio
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_market_022 import CurrentPluginMarket
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.typert.remote import RemoteError
from scripts.rc022_market_listing_probe import observe
from scripts import rc022_market_http_probe as http_probe


def provide_manager(ctx):
    async def bundles(): return []
    ctx.provide('pluginManager', SimpleNamespace(listBundles=bundles, listVersionExemptions=lambda: dict(exemptions={})))


@pytest.mark.asyncio
async def test_listing_annotations_paging_and_live_facts():
    rows = await observe(); by = {row['step']: row for row in rows}
    assert len(rows) == 18
    listing = {entry['name']: entry for entry in by['listing']['value']['entries']}
    assert listing['same']['installation']['status'] == 'installed'
    assert listing['older']['installation']['status'] == 'update-available'
    assert listing['shipped']['installation']['status'] == 'provided'
    assert listing['catalog']['installation']['status'] == 'not-installed'
    assert listing['exempted']['versions'][0]['compatibility'] == dict(compatible=False,
        runtimeVersion='0.2.2-rc.3', requirements={'engines.dsh': '0.0.1'}, exempted=True)
    assert 'defaultVersion' not in listing['exempted']
    assert listing['mixed']['defaultVersion'] == '1.0.0'
    assert 'defaultVersion' not in listing['only-preview-stable']
    assert [version['update'] for version in listing['from-git']['versions']] == [False, True, False, False, False]
    assert listing['hosted']['versions'][0]['update']
    assert listing['version-spelling-1']['installation']['status'] == 'different-version'
    assert listing['version-spelling-10']['installation']['status'] == 'update-available'
    assert by['unlisted']['value'] is None
    assert by['live-installation']['value']['entries'][0]['installation']['status'] == 'update-available'
    assert by['removed'] == dict(step='removed', indexes=[], changed=1, fetches=1, managerReads=6)


@pytest.mark.asyncio
async def test_actual_http_cache_search_and_entry_composition():
    server = http_probe.ThreadingHTTPServer(('127.0.0.1', 0), http_probe.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    ctx = Context(); provide_manager(ctx); url = 'http://127.0.0.1:'+str(server.server_port)+'/ok'
    try:
        await ctx.plugin(CurrentPluginMarket, dict(indexes=[url], detailCacheDir='/unused/market-cache'))
        market = ctx.pluginMarket; query = dict(sort=dict(kind='index'), offset=0, limit=100)
        first, second = await asyncio.gather(market.search(url, query), market.search(url, query))
        assert first == second
        assert first['title'] == 'Market' and first['entries'] == []
        assert len(market.documents.cache) == 1 and not market.documents.pending
        assert market.listIndexes() == [dict(url=url, title='Market')]
        assert await market.entry(url, 'unlisted') is None
        refreshed = await market.search(url, dict(query, refresh=True))
        assert refreshed['fetchedAt'] > first['fetchedAt']
    finally:
        await ctx.fiber.dispose(); server.shutdown(); server.server_close(); thread.join(2)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_unload_revokes_service_event_and_pending_read():
    ctx = Context(); provide_manager(ctx)
    fiber = ctx.plugin(CurrentPluginMarket, dict(indexes=['https://market.example/a'], detailCacheDir='/unused/market-cache'))
    await fiber; market = ctx.pluginMarket; changed = []; ctx.on('plugin-market/changed', lambda: changed.append(1))
    entered = asyncio.Event()
    async def fetch(url, signal):
        entered.set(); await signal.wait_aborted(); signal.throwIfAborted()
    market.documents.fetch_index = fetch
    task = asyncio.create_task(market.search('https://market.example/a', dict(sort=dict(kind='index'), offset=0, limit=1)))
    await entered.wait(); await fiber.dispose()
    with pytest.raises(RuntimeError, match='Plugin market disposed'): await task
    assert ctx.get('pluginMarket') is None
    ctx.emit('loader/volatile-update', [['indexes']])
    assert not changed and not market.documents.pending
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_settings_requires_profile_entry_after_url_admission():
    ctx = Context(); provide_manager(ctx)
    try:
        await ctx.plugin(CurrentPluginMarket, dict(detailCacheDir='/unused/market-cache'))
        with pytest.raises(RemoteError) as caught: await ctx.pluginMarket.setIndexes(['relative'])
        assert caught.value.code == 'plugin-market/invalid-index-url'
        with pytest.raises(RemoteError) as caught: await ctx.pluginMarket.setIndexes(['https://market.example/a'])
        assert caught.value.code == 'plugin-market/settings-unavailable'
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_profile_cache_directory_empty_override_resolves_profile(tmp_path):
    ctx = Context(); provide_manager(ctx); ctx.provide('profileContext', SimpleNamespace(dir=str(tmp_path)))
    try:
        await ctx.plugin(CurrentPluginMarket, dict(detailCacheDir=''))
        assert Path(ctx.pluginMarket.detail_cache_dir) == tmp_path
        assert not list(tmp_path.iterdir())
    finally: await ctx.fiber.dispose()


@pytest.mark.parametrize('patch', [dict(fetchTimeoutMs=0), dict(fetchTimeoutMs=2147483648), dict(maxBytes=0),
    dict(cacheTtlMs=-1), dict(indexes=['https://example.com/\ufeffx']), dict(detailNpmFileSources=[]), dict(detailNpmFileSources=['unknown'])])
def test_config_rejects_invalid_limits_sources(patch):
    with pytest.raises(Exception): CurrentPluginMarket.Config(patch)
