"""Pinned Market listing, document details and adjacent-image Remote service."""
import asyncio
import math
import os
import re
from urllib.parse import parse_qs, urlsplit

from dsh.boot.market_document_022 import MarketDocumentCache, normalize_index_url
from dsh.boot.market_detail_022 import MarketDetailReader
from dsh.boot.market_http_022 import MarketHttpReader
from dsh.boot.market_search_022 import MarketSearchWorker
from dsh.boot.market_listing_022 import listing_of
from dsh.boot.market_repository_022 import repository_of, manifest_repository
from dsh.boot.market_repository_cache_022 import RepositoryCache
from dsh.boot.market_repository_files_022 import RepositoryFiles
from dsh.boot.plugin_compatibility import get_dsh_runtime_version
from dsh.core.session.json import UNDEFINED
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.schema import Schema as z
from dsh.cordis.text import JS_WHITESPACE
from dsh.host.url_current import _url
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from dsh.typert.artifact import UNDEFINED as WIRE_UNDEFINED
from dsh.typert.stores import field
from dsh.util.plugin_detail import DetailFailure, detail_image_response, language_chain, npm_file_source_order
from dsh.util.plugin_detail_http import NpmFiles


def integer(value):
    try: return type(value) in (int, float) and math.isfinite(value) and int(value) == value
    except OverflowError: return False


class CurrentPluginMarket(TypertRemoteService):
    inject = ['pluginManager']
    Config = z.object(dict(
        indexes=z.array(z.string().pattern(re.compile('^https?://[^'+re.escape(JS_WHITESPACE)+']+$'))).default([]).volatile(),
        compatibleIndexes=z.array(z.string()).default([]),
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
        self.compatible_indexes = frozenset(normalize_index_url(url) for url in config.get('compatibleIndexes', []))
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
        self.searches = MarketSearchWorker(self.documents.lifetime.signal)
        self.repositories = RepositoryCache(dict(dir=cache_dir, maxRepositoryBytes=config['detailRepositoryMaxBytes'],
            maxCacheBytes=config['detailCacheMaxBytes'], timeoutMs=config['detailGitTimeoutMs'], ttlMs=config['cacheTtlMs'],
            transports=['https', 'http', 'ssh'], lifetime=self.documents.lifetime.signal, sizePollMs=200))
        self.details = MarketDetailReader(dict(maxDocumentBytes=config['detailMaxBytes'], maxImageBytes=config['detailImageMaxBytes'],
            ttlMs=config['cacheTtlMs']), self.detail_repository_options(), RepositoryFiles, manifest_repository)
        def register(scope):
            scope.effect(lambda: scope.get('connection').fetch.register(dict(path='/api/plugin-market/detail-file',
                methods=['GET'], requestBody='buffered', fetch=self.serve_detail_file)), 'plugin-market: detail-file')
        ctx.inject(['connection'], register)
        def updated(*_):
            self.documents.volatile_update()
            self.searches.retain(self.documents.cache)
            ctx.emit('plugin-market/changed')
        ctx.on('loader/volatile-update', updated)
        async def dispose():
            await self.documents.dispose()
            await asyncio.gather(self.searches.dispose(), self.repositories.settled(), *list(self.details.pending.values()), return_exceptions=True)
        ctx.effect(lambda: dispose, 'plugin-market owned reads')

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

    async def annotator(self, url):
        manager = self.owner.get('pluginManager')
        bundles = await await_callback_result(manager.listBundles())
        exemptions = manager.listVersionExemptions()['exemptions']
        runtime = get_dsh_runtime_version()
        native_compatible = self.owner.get('profilePackages') is None or url in self.compatible_indexes
        return lambda plugin: listing_of(plugin, bundles, exemptions, runtime, native_compatible)

    @Remote
    async def search(self, url, query):
        offset, limit = query.get('offset'), query.get('limit')
        if not integer(offset) or not 0 <= offset <= 9007199254740991:
            raise RemoteError('plugin-market/invalid-query', 'offset must be a non-negative integer', dict(field='offset', reason='range'))
        if not integer(limit) or not 1 <= limit <= 100:
            raise RemoteError('plugin-market/invalid-query', 'limit must be an integer from 1 to 100', dict(field='limit', reason='range'))
        document = await self.documents.document(url, query.get('refresh') is True, query.get('fetchedAt'))
        index = document['index']
        searches = self.searches
        if searches.closed:
            await asyncio.shield(searches.dispose())
            self.documents.lifetime.signal.throwIfAborted()
            if self.searches is searches:
                self.searches = MarketSearchWorker(self.documents.lifetime.signal)
        self.searches.retain(self.documents.cache)
        names = await self.searches.select(url, document, query)
        page = names[int(offset):int(offset+limit)]
        plugins = {plugin['name']: plugin for plugin in index['plugins']}
        listing = await self.annotator(url)
        next_offset = offset+len(page)
        return dict(url=url, title=index['title'], **({} if 'description' not in index else dict(description=index['description'])),
            metadata=index['metadata'], fetchedAt=document['fetchedAt'], entries=[listing(plugins[name]) for name in page],
            total=len(names), nextOffset=next_offset if next_offset < len(names) else None)

    async def entry(self, url, name):
        index = (await self.documents.document(url))['index']
        plugin = next((plugin for plugin in index['plugins'] if plugin['name'] == name), None)
        return None if plugin is None else (await self.annotator(url))(plugin)

    def detail_repository_options(self):
        return dict(timeoutMs=self.config['fetchTimeoutMs'], lifetime=self.documents.lifetime.signal,
            gitlabHosts=[host.lower() for host in self.config['detailGitlabHosts']], cache=self.repositories)

    @Remote
    async def readEntryDetail(self, url, name, version, language, options=None):
        try:
            languages = language_chain(language)
        except Exception as error:
            raise RemoteError('plugin-market/invalid-query', str(error), dict(field='language', reason='format'), cause=error)
        options = {} if options is None or options is WIRE_UNDEFINED or options is UNDEFINED else options
        index = (await self.documents.document(url))['index']
        plugin = next((candidate for candidate in index['plugins'] if candidate['name'] == name), None)
        listed = None if plugin is None else next((candidate for candidate in plugin['versions'] if candidate['version'] == version), None)
        if listed is None:
            raise RemoteError('plugin-market/unknown-plugin', url+' lists no '+name+'@'+version, dict(name=name, version=version))
        declared = plugin.get('repository')
        found = None if declared is None else repository_of(declared['url'])
        repository = None if found is None else dict(found, directory=declared.get('directory', ''))
        source = listed['source']
        if source['type'] == 'git':
            ref = repository_of(source['url'])
            if ref is None:
                return dict(status='none')
            directory = source.get('path', '')
            if repository is not None and repository['url'] == ref['url'] and repository['directory'] == directory:
                repository = None
            location = dict(files=RepositoryFiles(ref, source['commit'], self.detail_repository_options()), dir=directory, repository=repository)
        elif source.get('registry') is None or urlsplit(_url(source['registry'])['origin']).netloc in ('registry.npmjs.org', 'registry.npmmirror.com'):
            sources = npm_file_source_order(self.config['detailNpmFileSources'], options.get('npmFileSources', []))
            files = NpmFiles(name, version, sources, dict(timeoutMs=self.config['fetchTimeoutMs'], lifetime=self.documents.lifetime.signal))
            location = dict(files=files, dir='', repository=repository if repository is not None else 'manifest')
        else:
            location = dict(dir='', repository=repository)
        try:
            return await self.details.read(location, languages, options.get('refresh') is True)
        except DetailFailure as error:
            raise RemoteError('plugin-market/detail-unavailable', str(error), dict(reason=error.reason), cause=error)

    async def serve_detail_file(self, request):
        params = parse_qs(urlsplit(field(request, 'url')).query, keep_blank_values=True)
        cache = 'private, max-age='+str(self.config['cacheTtlMs']//1000)
        if 'document' not in params or 'path' not in params:
            return detail_image_response('invalid', cache)
        try:
            return detail_image_response(await self.details.image(params['document'][0], params['path'][0]), cache)
        except DetailFailure as error:
            return detail_image_response(error.reason, cache)
