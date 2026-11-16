"""Shared credential precedence and split provider configuration against Source."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_listed_catalog_probe import cases as protocol_cases


def cases():
    configs=protocol_cases()['configs']
    for key in ('modelsTimeoutMs','modelsMaxAgeMs'):
        for value in [None,False,0,-1,.5,1,2147483647,2147483648,9007199254740991,9007199254740992,10**400]: configs.append({key:value})
    for value in ['OTHER_KEY','bad key','key\n','',False,123,None]: configs.append(dict(apiKeyEnv=value))
    for value in [{}, {'remote':dict(name='Deploy',inputModalities=[])}, {'remote':dict(inputModalities=['text'],imageMaxBytes=1)},
                  {'remote':dict(imagePixelBudget='low')}, {'remote':dict(id='different')}, {'':{}}, {'remote':dict(maxTokens=0)}, None]:
        configs.append(dict(modelOverrides=value))
    credentials=[]
    for service in ['missing','absent','valid','blank','invisible','invalid','failure']:
        for ambient in [None,'ambient','', '  ']: credentials.append(dict(service=service,ambient=ambient))
    for raw in ['\ufeffvalid\ufeff','\u0085key\u0085','\u001ckey\u001c','\u2000key\u2000','raw\nkey','\u2028','valid!']:
        credentials.append(dict(service='custom',ambient='ambient',raw=raw))
    return dict(configs=configs,credentials=credentials)


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm.deepseek_route_config import resolveApiKeyOptions,resolveAccountOptions,routeSchema,plainOptions,plainAccountOptions
    from dsh.llm.deepseek_credentials import resolveDeepSeekApiKey,deepSeekApiKeyConfigured,resolveDeepSeekAccountToken,rejectDeepSeekAccountToken
    rows=[];inputs=cases()
    for kind,callback in [('apiKey',resolveApiKeyOptions),('account',resolveAccountOptions)]:
        for index,config in enumerate(inputs['configs']):
            try: result=dict(value=callback(config))
            except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
            rows.append(dict(kind=kind,index=index,**result))
    for kind,plain in [('apiKey',plainOptions),('account',plainAccountOptions)]:
        try:
            schema=routeSchema(kind)
            value=plain(schema({}))
            result=dict(value=value)
        except Exception as error: result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='parsed-defaults',name=kind,**result))
    for index,case in enumerate(inputs['credentials']):
        calls=[]
        def resolve(ref):
            calls.append(['resolve',ref])
            if case['service']=='failure': raise RuntimeError('store offline')
            value={'valid':'  stored  ','blank':'  ','invisible':'\ufeff','invalid':'bad\u0085key','custom':case.get('raw')}.get(case['service'])
            return None if case['service']=='absent' else dict(value=value)
        def describe(ref):
            calls.append(['describe',ref])
            if case['service']=='failure': raise RuntimeError('store offline')
            return dict(configured=case['service']!='absent')
        services=dict(launchEnvironment=SimpleNamespace(get=lambda key:None if case['ambient'] is None else dict(value=case['ambient'])))
        if case['service']!='missing': services['credentials']=SimpleNamespace(resolve=resolve,describe=describe)
        ctx=SimpleNamespace(get=services.get)
        outcome={}
        for name,callback in [('value',resolveDeepSeekApiKey),('configured',deepSeekApiKeyConfigured)]:
            try: outcome[name]=await callback(ctx,'TEST_KEY')
            except Exception as error: outcome[name]=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='credentials',index=index,calls=calls,**outcome))
    for mode in ['missing','valid','denied','resolve-error','reject-error']:
        calls=[]
        def resolve_token(endpoint):
            calls.append(['resolve',endpoint])
            if mode=='resolve-error': raise RuntimeError('account store offline')
            return None if mode=='denied' else 'account-token'
        def reject_token(token):
            calls.append(['reject',token])
            if mode=='reject-error': raise RuntimeError('remove failed')
        services={} if mode=='missing' else dict(deepseekAccount=SimpleNamespace(resolveToken=resolve_token,rejectToken=reject_token))
        ctx=SimpleNamespace(get=services.get)
        try: result=dict(value=await resolveDeepSeekAccountToken(ctx,'https://endpoint.example/messages'))
        except Exception as error: result=dict(error=str(error))
        await rejectDeepSeekAccountToken(ctx,'exact-rejected-token')
        rows.append(dict(kind='account-token',name=mode,calls=calls,**result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_deepseek_credentials.mts','Original/native split route resolvers and generated schemas/defaults; official-origin/built-in listing eligibility, '
        'credential ref grammar, cache timing, account overrides, authoritative credential service including absence/failure, presence without resolution, '
        'launch-environment fallback and JS key trim, destination-scoped account token and contained rejected-token persistence failure.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/deepseek_route_config.py',ROOT/'dsh/llm/deepseek_credentials.py',ROOT/'dsh/llm/llm_service.py',
         ROOT/'dsh/credentials/credentials.py',ROOT/'dsh/resources/deepseek_route_schemas_022.json'],prepare=prepare)
