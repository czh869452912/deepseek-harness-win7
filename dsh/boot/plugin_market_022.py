"""Candidate market listing service; detail methods are a subsequent contract."""
import math
import os
import re

from dsh.boot.market_document_022 import MarketDocumentCache
from dsh.boot.market_http_022 import MarketHttpReader
from dsh.boot.market_index_022 import observe_market_operations_async
from dsh.boot.market_listing_022 import listing_of
from dsh.boot.plugin_compatibility import get_dsh_runtime_version
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.schema import Schema as z
from dsh.cordis.text import JS_WHITESPACE
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from dsh.typert.stores import field


def integer(value):
    try: return type(value) in (int, float) and math.isfinite(value) and int(value) == value
    except OverflowError: return False


class CurrentPluginMarket(TypertRemoteService):
    inject = ['pluginManager']
    Config = z.object(dict(
        indexes=z.array(z.string().pattern(re.compile('^https?://[^'+re.escape(JS_WHITESPACE)+']+$'))).default([]).volatile(),
        fetchTimeoutMs=z.natural().min(1).max(2147483647).default(15000),
        maxBytes=z.natural().min(1).default(128*1024*1024), cacheTtlMs=z.natural().default(600000),
        detailMaxBytes=z.natural().min(1).default(1024*1024), detailImageMaxBytes=z.natural().min(1).default(5*1024*1024),
        detailRepositoryMaxBytes=z.natural().min(1).default(50*1024*1024), detailCacheMaxBytes=z.natural().min(1).default(500*1024*1024),
        detailCacheDir=z.string(), detailGitTimeoutMs=z.natural().min(1).max(2147483647).default(60000),
        detailNpmFileSources=z.array(z.union(['jsdelivr', 'unpkg', 'npmmirror'])).min(1).default(['jsdelivr', 'unpkg', 'npmmirror']),
        detailGitlabHosts=z.array(z.string()).default(['gitlab.com'])))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'pluginMarket')
        self.owner, self.config = ctx, config
        self.entry_id = field(field(getattr(ctx.fiber, 'entry', None), 'options'), 'id')
        profile = ctx.get('profileContext')
        cache_dir = config.get('detailCacheDir')
        if profile is not None:
            cache_dir = os.path.abspath(os.path.join(field(profile, 'dir'),
                cache_dir if cache_dir is not None else os.path.join('.plugin-market', 'repositories')))
        if cache_dir is None or not os.path.isabs(cache_dir):
            raise ValueError('plugin-market: detailCacheDir must be an absolute path when the service runs without a dsh profile')
        self.detail_cache_dir = cache_dir
        self.documents = MarketDocumentCache(lambda: self.config['indexes'].get(),
            MarketHttpReader(config['fetchTimeoutMs'], config['maxBytes']), config['cacheTtlMs'])
        def updated(*_):
            self.documents.volatile_update()
            ctx.emit('plugin-market/changed')
        ctx.on('loader/volatile-update', updated)
        ctx.effect(lambda: self.documents.dispose, 'plugin-market document reads')

    @Remote
    def listIndexes(self):
        return self.documents.list_indexes()

    @Remote
    async def setIndexes(self, urls):
        normalized = self.documents.normalize_replacement(urls)
        settings = self.owner.get('settings')
        if settings is None or self.entry_id is None:
            raise RemoteError('plugin-market/settings-unavailable', 'Index sources require the settings service and a profile entry', {})
        await await_callback_result(settings.update(self.entry_id, dict(indexes=normalized)))

    async def annotator(self):
        manager = self.owner.get('pluginManager')
        bundles = await await_callback_result(manager.listBundles())
        exemptions = manager.listVersionExemptions()['exemptions']
        runtime = get_dsh_runtime_version()
        return lambda plugin: listing_of(plugin, bundles, exemptions, runtime)

    @Remote
    async def search(self, url, query):
        offset, limit = query.get('offset'), query.get('limit')
        if not integer(offset) or not 0 <= offset <= 9007199254740991:
            raise RemoteError('plugin-market/invalid-query', 'offset must be a non-negative integer', dict(field='offset', reason='range'))
        if not integer(limit) or not 1 <= limit <= 100:
            raise RemoteError('plugin-market/invalid-query', 'limit must be an integer from 1 to 100', dict(field='limit', reason='range'))
        document = await self.documents.document(url, query.get('refresh') is True, query.get('fetchedAt'))
        index = document['index']
        row = (await observe_market_operations_async([dict(kind='search', value=index, url=url, selections=[query])], self.documents.lifetime.signal))[0]
        if not row['ok']:
            raise ValueError(row['error']['message'])
        names = row['results'][0]
        page = names[int(offset):int(offset+limit)]
        plugins = {plugin['name']: plugin for plugin in index['plugins']}
        listing = await self.annotator()
        next_offset = offset+len(page)
        return dict(url=url, title=index['title'], **({} if 'description' not in index else dict(description=index['description'])),
            metadata=index['metadata'], fetchedAt=document['fetchedAt'], entries=[listing(plugins[name]) for name in page],
            total=len(names), nextOffset=next_offset if next_offset < len(names) else None)

    async def entry(self, url, name):
        index = (await self.documents.document(url))['index']
        plugin = next((plugin for plugin in index['plugins'] if plugin['name'] == name), None)
        return None if plugin is None else (await self.annotator())(plugin)
