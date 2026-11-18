"""Account-aware native Messages search and its live canonical registration."""
import json
import inspect
import math
from pathlib import Path
from types import SimpleNamespace

from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.cordis.environment import launch_environment_of
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.cordis.volatile import is_volatile
from dsh.core.cancellation import aborted
from dsh.credentials.credentials import credential_ref
from dsh.host.url_current import _url
from dsh.llm.deepseek_credentials import resolveDeepSeekApiKey, deepSeekApiKeyConfigured, resolveDeepSeekAccountToken, rejectDeepSeekAccountToken
from dsh.typert.stores import field
from dsh.web.deepseek_search_provider import abortable, error_text, search_aborted, throw_if_search_aborted, map_anthropic_response
from dsh.web.deepseek_api_transport import fetchResponse, responseJson
from dsh.web.web_service import WebError


DEFAULTS = dict(apiKeyEnv='DEEPSEEK_API_KEY',model='deepseek-v4-flash',apiVersion='2023-06-01',maxTokens=4096,maxUses=5)
DEFAULT_BASE = 'https://api.deepseek.com/anthropic/v1'
Config = z.object({
    'apiKey':z.string().role('secret').volatile(), 'apiKeyEnv':z.string().role('credential-ref').default(DEFAULTS['apiKeyEnv']).volatile(),
    'baseURL':z.string().volatile(), 'model':z.string().default(DEFAULTS['model']).volatile(),
    'apiVersion':z.string().default(DEFAULTS['apiVersion']).volatile(),
    'maxTokens':z.number().step(1).min(1).default(4096).volatile(), 'maxUses':z.number().step(1).min(1).default(5).volatile(),
})


def endpointError(endpoint,message,cause=None):
    return WebError(message+'\n\nThe web request used endpoint '+stringify_json(endpoint)+'. '
        'Search endpoint configuration is separate from chat. If that endpoint is not intended, '
        'guide the user to Plugins > Built-in plugin settings > Web search and fetch, select DeepSeek (legacy) under Search, '
        'and change and save its Base URL. If that settings page is unavailable, the user can set '
        'web-search-deepseek.baseURL to a trusted DeepSeek endpoint. Only the user should choose or change the endpoint.',
        'WEB_PROVIDER_ERROR',cause=cause)


async def resolveCredential(resolve,signal):
    throw_if_search_aborted(signal)
    try:
        operation=resolve()
        if inspect.iscoroutine(operation): operation=start_coroutine(operation)
        return await abortable(operation,signal)
    except Exception as error:
        if aborted(signal) or getattr(error,'name',None)=='AbortError': raise search_aborted(signal,error)
        raise WebError('DeepSeek search credential resolution failed: '+error_text(error),'WEB_PROVIDER_ERROR',cause=error)


class DeepSeekSearchProvider:
    id='deepseek-official'
    with (Path(__file__).resolve().parents[1]/'resources/messages_search_description_022.json').open(encoding='utf-8') as _stream:
        description=json.load(_stream)

    def __init__(self,resolveOptions): self.resolveOptions=resolveOptions

    def available(self):
        options=self.resolveOptions()
        try: _url(options['baseURL'])
        except (ValueError,TypeError): return False
        def positive(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0 and int(value)==value
        credential=bool(options.get('apiKey')) or options.get('resolveApiKey') is not None or options.get('resolveAccountToken') is not None
        return credential and positive(options['maxTokens']) and positive(options['maxUses'])

    async def authHeaders(self,options,endpoint,signal):
        account=options.get('resolveAccountToken'); reject=options.get('rejectAccountToken')
        token=await resolveCredential(lambda:account(endpoint),signal) if account is not None else None
        if token is not None and len(token)>0:
            return dict(kind='account',headers={'x-dsh-auth-token':token},reject=(lambda:reject(token)) if reject is not None else None)
        throw_if_search_aborted(signal)
        key=options.get('apiKey')
        if not key:
            resolve=options.get('resolveApiKey')
            key=await resolveCredential(resolve,signal) if resolve is not None else None
        if key is None or len(key)==0:
            ref=options.get('apiKeyEnv');ref='DEEPSEEK_API_KEY' if ref is None else ref
            raise WebError('DeepSeek search has no API key for "'+ref+'"; store it through the credentials service'
                ' (the web Models page writes it), export it in the launching environment, or set a literal'
                ' "apiKey" in the web-search-deepseek config; a conversation using a DeepSeek Account model'
                ' searches with the account sign-in instead','WEB_PROVIDER_CREDENTIAL_MISSING')
        return dict(kind='api-key',headers={'x-api-key':key,'authorization':'Bearer '+key})

    def search(self,request,signal=None): return start_coroutine(self._search(request,signal))

    async def _search(self,request,signal):
        options=self.resolveOptions();endpoint=options['baseURL']+'/messages'
        auth=await await_callback_result(self.authHeaders(options,endpoint,signal));throw_if_search_aborted(signal)
        body=dict(model=options['model'],max_tokens=options['maxTokens'],messages=[dict(role='user',content=[
            dict(type='text',text='Perform a web search for the query: '+request['query'])])],
            tools=[dict(type='web_search_20250305',name='web_search',max_uses=options['maxUses'])],thinking=dict(type='disabled'))
        record=options.get('recordRequest')
        if record is not None: record(dict(endpoint=endpoint,apiVersion=options['apiVersion'],body=body))
        throw_if_search_aborted(signal)
        headers=dict(auth['headers'],**{'anthropic-version':options['apiVersion'],'content-type':'application/json',
                                      'accept':'application/json','user-agent':'deepseek-harness/0.0.1'})
        manager=fetchResponse(endpoint,headers,stringify_json(body),signal)
        try: response,chunks=await manager.__aenter__()
        except Exception as error:
            if aborted(signal) or getattr(error,'name',None)=='AbortError': raise search_aborted(signal,error)
            raise endpointError(endpoint,'DeepSeek search request failed: '+error_text(error),error)
        try:
            status=response['status']
            if not 200<=status<300:
                message='DeepSeek API error (HTTP '+str(status)+')';cancelled=None
                try:
                    parsed=await self.readJson(chunks,signal)
                    detail=parsed.get('error')
                    if not isinstance(detail,str):
                        detail=field(detail,'message')
                        if detail is None: detail=field(parsed,'message')
                    if isinstance(detail,str) and detail: message+=': '+detail
                except Exception as error:
                    if aborted(signal) or getattr(error,'name',None)=='AbortError': cancelled=search_aborted(signal,error)
                if status==401 and auth['kind']=='account':
                    try:
                        if auth['reject'] is not None: await await_callback_result(auth['reject']())
                    except Exception: pass
                    raise cancelled or WebError(message+'\n\nDeepSeek rejected the account sign-in used for this web search. '
                        'Guide the user to sign in to DeepSeek again; the search endpoint does not need changing.','WEB_PROVIDER_ERROR')
                if cancelled is not None: raise cancelled
                raise endpointError(endpoint,message)
            try: return map_anthropic_response(await self.readJson(chunks,signal))
            except Exception as error:
                if aborted(signal) or getattr(error,'name',None)=='AbortError': raise search_aborted(signal,error)
                if isinstance(error,WebError): message=error.message
                else:
                    message='DeepSeek returned an unprocessable response body: '+error_text(error)
                raise endpointError(endpoint,message,error)
        finally: await manager.__aexit__(None,None,None)

    async def readJson(self,chunks,signal):
        try: return await responseJson(chunks)
        except (json.JSONDecodeError,ValueError) as error:
            failure=SyntaxError(str(error));failure.name='SyntaxError';raise failure from error
        except Exception as error:
            if aborted(signal): raise
            raise TypeError('terminated') from error


def resolveOptions(ctx,config):
    ref=credential_ref(config['apiKeyEnv'])
    async def account(endpoint):
        agents=ctx.get('agents');agent=agents.currentInitiator() if agents is not None else None
        session=field(agent,'session');route=field(session.requestContext(),'provider') if session is not None else None
        return await resolveDeepSeekAccountToken(ctx,endpoint) if route=='deepseek-account' else None
    def record(request):
        agents=ctx.get('agents');agent=agents.currentInitiator() if agents is not None else None
        if agent is not None: agent.session.append('web/deepseek-search-llm-request',request)
    base=config.get('baseURL')
    if base is None: base=field(launch_environment_of(ctx).get('DEEPSEEK_SEARCH_BASE_URL'),'value',DEFAULT_BASE)
    if base is None: base=DEFAULT_BASE
    options=dict(config,apiKeyEnv=ref,baseURL=base,resolveAccountToken=account,
                 rejectAccountToken=lambda token:rejectDeepSeekAccountToken(ctx,token),resolveApiKey=lambda:resolveDeepSeekApiKey(ctx,ref),recordRequest=record)
    if not options.get('apiKey'): options.pop('apiKey',None)
    return options


async def searchConfigured(ctx,options,route=None):
    account=ctx.get('deepseekAccount')
    if route=='deepseek-account' and account is not None:
        try: token=await await_callback_result(account.resolveToken(options['baseURL']+'/messages'))
        except Exception: return False
        if token is not None and len(token)>0:return True
    if options.get('apiKey') is not None:return True
    try:return await deepSeekApiKeyConfigured(ctx,options['apiKeyEnv'])
    except Exception:return False


class CurrentWebSearchDeepSeek(Plugin):
    id='web-search-deepseek'
    inject=['web']
    Config=Config

    def apply(self,ctx):
        def options():
            values={}
            for key,item in self.config.items():
                item=item.get() if is_volatile(item) else item
                values[key]=None if item is _UNDEFINED else item
            return resolveOptions(ctx,values)
        provider=DeepSeekSearchProvider(options)
        row=SimpleNamespace(id=provider.id,description=provider.description,available=provider.available,
                            ready=lambda route=None:searchConfigured(ctx,options(),route),search=provider.search)
        ctx.effect(lambda:ctx.web.registerSearchProvider(row))
