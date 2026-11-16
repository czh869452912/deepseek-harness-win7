import copy
import json

import pytest

from dsh.llm.deepseek_config_current import resolveAdapterOptions,isBuiltInCatalog
from dsh.llm.listed_catalog import resolveListedCatalog,refuseListedModel
from dsh.llm.llm_service import LlmError
from dsh.llm.model_listing import parseModelListing
from scripts import rc022_listed_catalog_probe as corpus


@pytest.mark.asyncio
async def test_split_settings_and_listed_catalog_corpus(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'listed-catalog-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==1530
    config=next(row for row in rows if row['kind']=='config' and row['index']==0)
    assert config['builtIn'] and len(config['value']['models'])==2
    assert config['value']['baseURL']=='https://api.deepseek.com/anthropic'
    assert config['value']['models'][0]['toolUpdate']=='addition-only'
    offered=[row for row in rows if row['kind']=='catalog' and row.get('value',{}).get('offered')]
    assert offered and any(row['value']['badges'] for row in offered)
    assert any(any(refusal['code']=='CLIENT_UPGRADE_REQUIRED' for refusal in row.get('refused',{}).values()) for row in rows)
    assert any(row.get('value',{}).get('overrideErrors') for row in rows)


def test_resolved_settings_and_catalog_do_not_retain_mutable_inputs():
    raw=dict(models=[dict(id='custom',inputModalities=['image'],imagePixelBudget='low')],retryPolicy=dict(mode='normal',retryableCodes=['CUSTOM']))
    options=resolveAdapterOptions(raw)
    before=copy.deepcopy(options)
    raw['models'][0]['inputModalities'].append('text');raw['retryPolicy']['retryableCodes'].append('OTHER')
    assert options==before and options['models'][0]['imagePixelBudget']=='low'
    assert options['models'][0]['imageMaxBytes']==2097152
    options['models'].clear();options['retryPolicy']['retryableCodes'].clear()
    assert len(resolveAdapterOptions({})['models'])==2
    assert isBuiltInCatalog(resolveAdapterOptions({})['models'])
    assert not isBuiltInCatalog(resolveAdapterOptions({})['models'][::-1])


def test_environment_endpoint_and_explicit_endpoint_precedence():
    environment={'DEEPSEEK_BASE_URL':dict(value='http://localhost:8000/anthropic')}
    assert resolveAdapterOptions({},environment)['baseURL']=='http://localhost:8000/anthropic'
    assert resolveAdapterOptions(dict(baseURL='https://deployment.example/messages'),environment)['baseURL']=='https://deployment.example/messages'


def test_unknown_version_gate_and_pre_network_refusal_with_resolution_retained():
    supported=resolveAdapterOptions({})['models']
    listing=parseModelListing(dict(data=[dict(id='deepseek-flash',client_requirements={'deepseek-harness':dict(min_version='9.0.0')},api_capabilities=dict(anthropic_messages={}))]))['entries']
    catalog=resolveListedCatalog(dict(listing=listing,supported=supported,overrides={},routeMaxTokens=512,clientVersion='0.2.2-rc.3'))
    assert not catalog['offered'] and len(catalog['resolution'])==2
    with pytest.raises(LlmError) as raised:
        refuseListedModel('deepseek-flash',catalog['refusals']['deepseek-flash'])
    assert raised.value.code=='CLIENT_UPGRADE_REQUIRED'
    refuseListedModel('other',None)
