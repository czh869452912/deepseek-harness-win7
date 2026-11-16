"""Live Web selection, picker Remote and contained registry notifications."""
import asyncio
import inspect

from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.cordis.volatile import is_volatile
from dsh.typert.remote import TypertRemoteService, Remote
from dsh.typert.stores import field
from dsh.web.web_service import WebService, WebError


class CurrentWebService(WebService, TypertRemoteService):
    Config = z.object({'searchProvider': z.string().volatile(), 'fetchProvider': z.string().volatile()})

    def __init__(self, ctx, config=None):
        self._selectionConfig = config or {}
        super().__init__(ctx, {})

    def _selected(self, key, fallback):
        value = self._selectionConfig.get(key)
        if is_volatile(value): value = value.get()
        return fallback if value is None or value is _UNDEFINED else value

    @property
    def search_provider_id(self): return self._selected('searchProvider', self._searchProviderEnv)

    @search_provider_id.setter
    def search_provider_id(self, value): self._searchProviderEnv = value

    @property
    def fetch_provider_id(self): return self._selected('fetchProvider', self._fetchProviderEnv)

    @fetch_provider_id.setter
    def fetch_provider_id(self, value): self._fetchProviderEnv = value

    @Remote
    def listProviders(self):
        def rows(store):
            result = []
            for identifier, provider in store.items():
                row = dict(id=identifier)
                for key in ('title', 'description'):
                    value = field(provider, key, _UNDEFINED)
                    if value is not _UNDEFINED: row[key] = value
                result.append(row)
            return result
        return dict(search=rows(self.search_providers), fetch=rows(self.fetch_providers))

    def _warnListener(self, error):
        self.ctx.logger.warn('web: a web/providers-changed listener failed')
        self.ctx.logger.warn(error)

    def _emitChanged(self):
        for listener in self.ctx.events._dispatch_hooks('emit', 'web/providers-changed', self.ctx):
            try:
                returned = listener()
                if inspect.isawaitable(returned):
                    future = start_coroutine(returned) if inspect.iscoroutine(returned) else asyncio.ensure_future(returned)
                    def observed(done):
                        try: done.result()
                        except BaseException as error: self._warnListener(error)
                    future.add_done_callback(observed)
            except Exception as error:
                self._warnListener(error)

    def _register_provider(self, store, legacy_store, provider_id, provider, legacy):
        if provider_id in store:
            raise WebError('a web provider with id "'+provider_id+'" is already registered', 'WEB_DUPLICATE_PROVIDER')
        active = [True]
        def setup():
            store[provider_id] = provider; legacy_store[provider_id] = legacy
            self._emitChanged()
            def cleanup():
                if active[0] and store.get(provider_id) is provider:
                    del store[provider_id]; legacy_store.pop(provider_id, None)
                    self._emitChanged()
                active[0] = False
            return cleanup
        dispose_effect = self.ctx.effect(setup, label='web.registerProvider()')
        def dispose():
            pending = dispose_effect()
            if inspect.isawaitable(pending):
                try:
                    asyncio.get_running_loop()
                    asyncio.ensure_future(pending)
                except RuntimeError: asyncio.run(pending)
        return dispose

    async def _ready(self, store, selected, provider):
        try: _, row = self._resolve_provider(store, selected)
        except Exception: return True
        callback = getattr(row, 'ready', None)
        if callback is None: return True
        result = await await_callback_result(callback(provider))
        return True if result is None else result

    async def searchReady(self, provider=None):
        return await self._ready(self.search_providers, self.search_provider_id, provider)

    async def fetchReady(self, provider=None):
        return await self._ready(self.fetch_providers, self.fetch_provider_id, provider)
