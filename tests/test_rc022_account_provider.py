import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.llm.deepseek_provider_current import CurrentDeepSeekApiKeyProvider, CurrentDeepSeekAccountProvider
from dsh.llm.runtime_current import CurrentLlmRuntime
from scripts import rc022_account_provider_probe as corpus


@pytest.mark.asyncio
async def test_actual_account_catalog_and_request_error_mapping(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'account-provider-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 14
    assert all(row['afterDispose'] == dict(providers=[], directory=[]) for row in rows)
    authorized = rows[1]['auth']
    assert authorized['headers'] == {'x-dsh-auth-token': 'account-token'}
    assert [row['failure']['code'] for row in authorized['mapped'][:4]] == ['ACCOUNT_QUOTA', 'ACCOUNT_TOKEN_INVALID', 'AUTH', 'SERVER']
    assert authorized['mapped'][0]['causeSame'] and authorized['mapped'][1]['causeSame']
    assert rows[-1]['auth']['mapped'][1]['failure']['code'] == 'ACCOUNT_TOKEN_INVALID'
    assert 'error' in rows[9]['directory'][0]


@pytest.mark.asyncio
async def test_account_and_api_key_routes_mount_and_unload_independently():
    ctx = Context()
    async def resolve(ref): return dict(value='fixture-api-key')
    ctx.set_service('credentials', SimpleNamespace(resolve=resolve))
    try:
        await ctx.plugin(CurrentLlmRuntime)
        api = await ctx.plugin(CurrentDeepSeekApiKeyProvider, dict(models=[dict(id='configured-model')]))
        account = await ctx.plugin(CurrentDeepSeekAccountProvider)
        assert [row['id'] for row in ctx.llm.list_providers()] == ['deepseek-official', 'deepseek-account']
        assert await ctx.llm.list_models('deepseek-account') == []
        assert (await ctx.llm.list_models('deepseek-official'))[0]['id'] == 'configured-model'
        await account.dispose()
        assert [row['id'] for row in ctx.llm.list_providers()] == ['deepseek-official']
        assert [row['provider'] for row in ctx.llm.listConfigurableProviders()] == ['deepseek-official']
        await api.dispose()
        assert ctx.llm.list_providers() == [] and ctx.llm.listConfigurableProviders() == []
    finally: await ctx.fiber.dispose()
