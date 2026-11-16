import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.volatile import WRITE
from dsh.typert.remote import remote_methods
from dsh.web.web_service_current import CurrentWebService
from dsh.web.web_service import WebError
from scripts.rc022_web_api_selection_probe import observe


@pytest.mark.asyncio
async def test_route_ownership_billing_override_and_registry_lifetime_corpus(tmp_path):
    rows = await observe()
    (tmp_path/'web-selection-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 456
    assert all(row['changes'] == 4 and row['afterDispose'] == dict(search=[], fetch=[]) for row in rows)
    assert all(len(row['sent']) <= 1 for row in rows)
    assert 'legacy-must-ignore' not in json.dumps(rows)
    for row in rows:
        for sent in row['sent']:
            if sent['token'] is not None: assert sent['authorization'] is None
            if 'ori_question' in sent['body']: assert sent['body']['ori_question'] == 'first question'


@pytest.mark.asyncio
async def test_live_selection_ready_and_contained_listener_failures():
    ctx = Context(); changes = []; warnings = []; rows = {}
    def failed(): raise RuntimeError('listener-failed')
    async def asyncFailed(): raise RuntimeError('async-listener-failed')
    ctx.on('web/providers-changed', failed); ctx.on('web/providers-changed', asyncFailed)
    ctx.on('web/providers-changed', lambda: changes.append('changed'))
    ctx.logger.warn = lambda *args: warnings.append(args)
    class Providers(Plugin):
        inject = ['web']
        def apply(self, child):
            async def search(request, signal=None): return dict(sources=[], truncated=False)
            async def notReady(provider): return False
            for identifier in ('one', 'two'):
                row = SimpleNamespace(id=identifier, available=lambda: True, search=search)
                if identifier == 'one': row.ready = notReady
                rows[identifier] = row
                child.web.registerSearchProvider(row)
    try:
        fiber = await ctx.plugin(CurrentWebService, dict(searchProvider='one'))
        owner = await ctx.plugin(Providers)
        assert ctx.web.typertRemote['namespace'] == 'web'
        assert [row['method'] for row in remote_methods(ctx.web)] == ['listProviders']
        assert await ctx.web.searchReady('deepseek-account') is False
        assert len(ctx.web.listProviders()['search']) == 2 and len(changes) == 2
        selected = fiber.effectiveConfig['searchProvider']
        getattr(selected, WRITE)('two')
        assert await ctx.web.searchReady() is True
        getattr(selected, WRITE)('missing')
        assert await ctx.web.searchReady() is True
        with pytest.raises(WebError) as caught: await ctx.web.search(dict(query='fixture'))
        assert caught.value.code == 'WEB_PROVIDER_CONFIGURED_MISSING'
        await owner.dispose()
        for _ in range(5): await asyncio.sleep(0)
        assert len(changes) == 4 and len(warnings) >= 8
        assert ctx.web.listProviders() == dict(search=[], fetch=[])
    finally: await ctx.fiber.dispose()
