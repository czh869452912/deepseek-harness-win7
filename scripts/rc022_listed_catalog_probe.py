"""Split protocol settings and listed-catalog decisions against fixed Source."""
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    configs=[{},dict(protocol=None),dict(thinking='disabled',reasoningEffort='high'),dict(thinking='disabled',reasoningEffort='off')]
    keys=['defaultContextWindow','maxTokens','streamIdleTimeoutMs','maxRequestFilesBytes','maxInlineRequestImageBytes','maxImagesPerRequest',
          'imageOffloadByteQuantum','inlineImageOffloadByteQuantum','imageOffloadCountQuantum','filesApiTimeoutMs',
          'fileExpiresAfterSeconds','fileRefreshMarginSeconds','fileQuotaCleanupBatch']
    for key in keys:
        for value in [None,False,0,-1,.5,1,1.0,3600,2147483647,2147483648,9007199254740991,9007199254740992,10**400]: configs.append({key:value})
    for url in ['https://api.deepseek.com/anthropic','http://127.1/v1','http://[::1]:80/a','HTTP:\\EXAMPLE.com\\path',
                'https://example.com?','https://example.com#','https://@example.com/root','https://user@example.com',
                'https://example.com?x=1','https://example.com#hash','ftp://example.com','bad']:
        configs.append(dict(baseURL=url))
    model_layers=[{},dict(name=''),dict(contextWindow=0),dict(contextWindow=1.0),dict(maxTokens=9007199254740992),
        dict(inputModalities=[]),dict(inputModalities=['text','text']),dict(inputModalities=['image']),dict(inputModalities=['image','text']),
        dict(imageDetail=None),dict(inputModalities=['text'],imageMaxBytes=1),dict(inputModalities=['image'],imagePixelBudget='low'),
        dict(inputModalities=['image'],imagePixelBudget=0),dict(inputModalities=['image'],imageMaxBytes=0),
        dict(systemPromptUpdate=None),dict(systemPromptUpdate='leading-only'),dict(systemPromptUpdate='in-history'),
        dict(toolUpdate='addition-only'),dict(toolUpdate='in-history'),dict(toolUpdate='leading-only'),dict(unrecognized=1)]
    for layer in model_layers: configs.append(dict(models=[dict(id='a',**layer)]))
    configs.extend([dict(models=[]),dict(models=None),dict(models=[dict(id='')]),dict(models=[dict(id='a'),dict(id='a')])])
    for mode in ('normal','always','bad'):
        configs.append(dict(retryPolicy=dict(mode=mode)))
        for key,values in [('maxRetries',[None,-1,0,.5,9007199254740992]),('retryableCodes',[None,[],[''],['X','X'],['OTHER']]),
            ('backoff',[None,{},dict(initialDelayMs=0),dict(maxDelayMs=1),dict(jitterRatio=2),dict(unrecognized=1)]),('unrecognized',[1])]:
            for value in values: configs.append(dict(retryPolicy=dict(mode=mode,**{key:value})))
    catalogs=[dict(rows=None,overrides={}),dict(rows=None,overrides={'missing':dict(contextWindow=1)}),dict(rows=[],overrides={})]
    requirements=[{},dict(client_requirements=None),dict(client_requirements={'deepseek-harness':{}})]
    for version in ['0.2.0-rc.1','0.2.2-rc.3','0.2.2','1.0.0','invalid',' 0.2.2-rc.3 ','v0.2.2-rc.3','1.02.3',None]:
        requirements.append(dict(client_requirements={'deepseek-harness':dict(min_version=version)}))
    capabilities=[{},dict(api_capabilities=dict(anthropic_messages={})),dict(input_modalities=['image'],api_capabilities=dict(anthropic_messages={})),
        dict(context_window=500000,max_output_tokens=4096,input_modalities=['text'],api_capabilities=dict(anthropic_messages=dict(system_prompt_update='leading-only',tool_update='leading-only'))),
        dict(input_modalities=['image','text'],api_capabilities=dict(anthropic_messages=dict(system_prompt_update='in-history',tool_update='addition-only')))]
    override_layers=[{},dict(name='Deploy',maxTokens=512),dict(contextWindow=0),dict(inputModalities=['text']),
        dict(inputModalities=['image'],imagePixelBudget='low'),dict(inputModalities=[]),dict(toolUpdate='bad')]
    for model_id in ('deepseek-flash','deepseek-v4-pro','remote-only'):
        for requirement in requirements:
            for capability in capabilities:
                for layer in override_layers:
                    catalogs.append(dict(rows=[dict(id=model_id,**requirement,**capability)],
                        overrides={model_id:layer,'not-described':dict(name='X')},clientVersion='0.2.2-rc.3'))
    catalogs.extend([
        dict(rows=[dict(id='deepseek-v4-pro',api_capabilities=dict(anthropic_messages={})),dict(id='deepseek-flash',api_capabilities=dict(anthropic_messages={}))],overrides={}),
        dict(rows=[dict(id='deepseek-flash',api_capabilities=dict(anthropic_messages={}),client_metadata={'deepseek-harness':dict(badge=dict(text='New',tone='info'))})],overrides={}),
        dict(rows=[dict(id='deepseek-flash',api_capabilities=dict(anthropic_messages={}),client_metadata={'deepseek-harness':dict(badge=dict(text='a'*13))})],overrides={}),
    ])
    return dict(configs=configs,catalogs=catalogs)


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh import __version__
    from dsh.llm.deepseek_config_current import resolveAdapterOptions,isBuiltInCatalog
    from dsh.llm.model_listing import parseModelListing
    from dsh.llm.listed_catalog import resolveListedCatalog,refuseListedModel
    rows=[];inputs=cases()
    for index,config in enumerate(inputs['configs']):
        try:
            value=resolveAdapterOptions(config)
            result=dict(value=value,builtIn=isBuiltInCatalog(value['models']))
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='config',index=index,**result))
    supported=resolveAdapterOptions({})['models']
    for index,case in enumerate(inputs['catalogs']):
        try:
            listing=None if case['rows'] is None else parseModelListing(dict(data=case['rows']))['entries'] if case['rows'] else []
            value=resolveListedCatalog(dict(listing=listing,supported=copy.deepcopy(supported),overrides=case['overrides'],routeMaxTokens=256000,clientVersion=case.get('clientVersion','0.2.2-rc.3')))
            refused={}
            for model_id,refusal in value['refusals'].items():
                try: refuseListedModel(model_id,refusal)
                except Exception as error:
                    assert error.message.endswith('current version is '+__version__)
                    refused[model_id]=dict(error=error.message[:-len(__version__)]+'<active-runtime>',code=error.code)
            result=dict(value=value,refused=refused)
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='catalog',index=index,**result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_listed_catalog.mts','Original/native split Messages settings, model defaults and validation, retry policy bounds and inactive fields; '
        'listed catalog availability by client version and build knowledge, capability layering/output cap, overrides with invalid override fallback, '
        'unlisted supported request resolution, badge diagnostics, and pre-network refusal facts. Runtime refusal versions are independently verified before marking.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/deepseek_config_current.py',ROOT/'dsh/llm/retry_config_current.py',ROOT/'dsh/llm/listed_catalog.py',ROOT/'dsh/resources/deepseek_defaults_022.json'],prepare=prepare)
