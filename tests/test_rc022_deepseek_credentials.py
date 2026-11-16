import json

import pytest

from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.cordis.volatile import WRITE
from dsh.credentials.credentials import credential_ref,is_credential_ref_name
from dsh.credentials.credentials_local import CredentialsService
from dsh.llm.deepseek_credentials import resolveDeepSeekApiKey,deepSeekApiKeyConfigured
from dsh.llm.deepseek_route_config import routeSchema,plainOptions,resolveApiKeyOptions,resolveAccountOptions
from dsh.llm.llm_service import normalize_api_key
from scripts import rc022_deepseek_credentials_probe as corpus


@pytest.mark.asyncio
async def test_split_route_credentials_and_schema_corpus(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'deepseek-credentials-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==644
    creds=[row for row in rows if row['kind']=='credentials']
    assert any(row['value'] is None and row['configured'] is False and len(row['calls'])==2 for row in creds)
    assert any(row['configured'] is True and isinstance(row['value'],dict) and row['value']['code']=='INVALID_CREDENTIAL' for row in creds)
    schemas=[row for row in rows if row['kind']=='parsed-defaults']
    assert len(schemas)==2 and all('value' in row for row in schemas)
    assert all('error' not in row for row in rows if row['kind']=='account-token' and row['name']=='reject-error')


def test_source_schemas_reject_non_string_key_and_resolve_volatile_defaults():
    schema=routeSchema('apiKey')
    with pytest.raises(Exception): schema(dict(apiKeyEnv=False))
    config=schema({})
    options=resolveApiKeyOptions(plainOptions(config))
    assert options['listing']==dict(url='https://api.deepseek.com/models',timeoutMs=5000,maxAgeMs=600000)
    getattr(config['apiKeyEnv'],WRITE)('DEPLOYMENT_KEY')
    assert resolveApiKeyOptions(plainOptions(config))['apiKeyEnv']=='DEPLOYMENT_KEY'
    account=resolveAccountOptions(plainOptions(routeSchema('account')({})))
    assert account['modelOverrides']=={} and account['catalog']['url']=='https://api.deepseek.com/models'


@pytest.mark.asyncio
async def test_real_credentials_service_owns_launch_snapshot_and_helper_reads(tmp_path):
    ctx=Context()
    ctx.set_service('launchEnvironment',LaunchEnvironmentSnapshot([dict(source='process',values={'TEST_KEY':'  launch-key  '})]))
    CredentialsService(ctx,credentials_file=str(tmp_path/'credentials.yaml'))
    try:
        assert await resolveDeepSeekApiKey(ctx,'TEST_KEY')=='launch-key'
        assert await deepSeekApiKeyConfigured(ctx,'TEST_KEY')
        assert await resolveDeepSeekApiKey(ctx,'MISSING_KEY') is None
        assert not await deepSeekApiKeyConfigured(ctx,'MISSING_KEY')
    finally: await ctx.fiber.dispose()


@pytest.mark.parametrize('raw,valid', [('\ufeff key \ufeff',True),('\u2000key\u2000',True),('\u0085key\u0085',False),('\u001ckey\u001c',False),('key\nsecond',False)])
def test_api_key_js_trim_boundary(raw,valid):
    assert normalize_api_key(raw)['ok'] is valid


def test_credential_reference_full_boundary():
    assert credential_ref('TEST_KEY')=='TEST_KEY'
    assert not is_credential_ref_name('TEST_KEY\n')
    with pytest.raises(TypeError,match='must match /'):
        credential_ref('TEST_KEY\n')
