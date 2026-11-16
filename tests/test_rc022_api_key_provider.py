import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.volatile import WRITE
from dsh.llm.deepseek_provider_current import CurrentDeepSeekApiKeyProvider
from dsh.llm.runtime_current import CurrentLlmRuntime
from scripts import rc022_api_key_provider_probe as corpus


@pytest.mark.asyncio
async def test_actual_api_key_mount_discovery_and_live_credentials(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'api-key-provider-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 20
    assert all(row['afterDispose'] == dict(providers=[], directory=[]) for row in rows)
    assert rows[2]['results'][0]['models'][0]['id'] == 'configured-model'
    assert rows[3]['results'][0]['error']['code'] == 'INVALID_CREDENTIAL'
    assert rows[14]['results'][1]['models'] == [] and rows[14]['calls'][-1] == 'OTHER_KEY'


@pytest.mark.asyncio
async def test_class_mount_and_late_settings_presentation_are_reversible():
    ctx = Context(); events = []
    async def resolve(ref): return dict(value='fixture-key')
    ctx.set_service('credentials', SimpleNamespace(resolve=resolve))
    try:
        await ctx.plugin(CurrentLlmRuntime)
        await ctx.plugin(CurrentDeepSeekApiKeyProvider, dict(models=[dict(id='configured-model')]))
        assert (await ctx.llm.list_models('deepseek-official'))[0]['id'] == 'configured-model'
        def configure(policy, owner):
            events.append(dict(policy=policy, ownerActive=owner.state.value if hasattr(owner.state, 'value') else str(owner.state)))
            return lambda: events.append('disposed')
        ctx.set_service('settings', SimpleNamespace(configure=configure))
        for _ in range(20):
            if events: break
            await asyncio.sleep(0)
        assert len(events) == 1 and events[0]['policy'] == dict(auto=False)
        llm = ctx.llm
    finally: await ctx.fiber.dispose()
    assert events[-1] == 'disposed'
    assert llm.list_providers() == [] and llm.listConfigurableProviders() == []


@pytest.mark.asyncio
async def test_current_configuration_error_does_not_reuse_last_good_options():
    ctx = Context(); config = CurrentDeepSeekApiKeyProvider.Config(dict(models=[dict(id='configured-model')]))
    plugin = CurrentDeepSeekApiKeyProvider(config=config)
    def mount(child): return plugin.apply(child)
    mount.inject = ['llm']
    try:
        await ctx.plugin(CurrentLlmRuntime); await ctx.plugin(mount)
        assert plugin.adapter.options()['models'][0]['id'] == 'configured-model'
        getattr(config['baseURL'], WRITE)('not-an-http-url')
        with pytest.raises(ValueError): plugin.adapter.options()
        ctx.emit('loader/volatile-update')
        with pytest.raises(ValueError): await plugin.adapter.resolveModel('deepseek-official', 'configured-model')
    finally: await ctx.fiber.dispose()
