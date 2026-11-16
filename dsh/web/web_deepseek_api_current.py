"""Live route-aware credential selection for the direct DeepSeek web APIs."""
from types import SimpleNamespace

from dsh.cordis.environment import launch_environment_of
from dsh.cordis.fiber import FiberState
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.credentials.credentials import credential_ref
from dsh.host.url_current import _url
from dsh.llm.deepseek_config_current import plainOptions
from dsh.llm.deepseek_credentials import deepSeekApiKeyConfigured, resolveDeepSeekApiKey, resolveDeepSeekAccountToken, rejectDeepSeekAccountToken
from dsh.llm.deepseek_route_config import resolveApiKeyOptions, resolveAccountOptions
from dsh.typert.stores import field
from dsh.web.deepseek_api_providers import DeepSeekSearchApiProvider, DeepSeekFetchApiProvider, DEEPSEEK_WEB_API_BASE_URL
from dsh.web.deepseek_api_transport import isDeepSeekWebAuthReady

NAME = 'web-deepseek-api'
ACCOUNT = 'deepseek-account'
OFFICIAL = 'deepseek-official'
ROUTE_PACKAGES = {OFFICIAL: '@deepseek-ai/dsh-llm-deepseek-api-key', ACCOUNT: '@deepseek-ai/dsh-llm-deepseek-account'}
Config = z.object({
    'count': z.number().step(1).min(1).max(50).default(10).volatile(),
    'searchRequestsPerSecond': z.number().step(1).min(1).default(5).volatile(),
    'sendOriginalQuestion': z.boolean().default(True).volatile(),
    'searchBilling': z.union(['auto', 'account', 'api-key']).default('auto').volatile(),
    'fetchBilling': z.union(['auto', 'account', 'api-key']).default('auto').volatile(),
    'searchBaseURL': z.string().volatile(),
    'searchApiKeyEnv': z.string().role('credential-ref').volatile(),
    'fetchBaseURL': z.string().volatile(),
    'fetchApiKeyEnv': z.string().role('credential-ref').volatile(),
})


def routeConfig(ctx, provider):
    llm, loader = ctx.get('llm'), ctx.get('loader')
    if llm is None or loader is None or not any(row['id'] == provider for row in llm.listProviders()): return None
    directory = next((row for row in llm.listConfigurableProviders() if row['provider'] == provider), None)
    if directory is None or len(directory['settingsPath']) != 0: return None
    entry = next((entry for entry in loader.entries() if field(entry, 'options').get('id') == directory['settingsNs']
                  and field(entry, 'options').get('name') == ROUTE_PACKAGES[provider]), None)
    fiber = field(entry, 'fiber')
    return field(fiber, 'effectiveConfig') if field(fiber, 'state') == FiberState.ACTIVE else None


def toolsBase(base):
    return _url(base)['origin']+'/v1/tools'


def apiKeySource(ctx, base, ref):
    return dict(kind='api-key', baseURL=base, key=dict(ref=ref,
        configured=lambda: deepSeekApiKeyConfigured(ctx, ref), resolve=lambda: resolveDeepSeekApiKey(ctx, ref)))


def misconfigured(capability, route, error):
    subject = capability.title(); prefix = capability
    provider = 'DeepSeek account model provider' if route == ACCOUNT else 'DeepSeek API-key model provider'
    credential = 'the DeepSeek account sign-in' if route == ACCOUNT else "that provider's API key"
    message = getattr(error, 'message', str(error))
    return dict(kind='misconfigured', message='DeepSeek '+subject+' API sends '+credential+' to the origin of the '+provider+', and'
        +" that provider's settings do not resolve: "+message+'. '+subject+' did not send the request. Guide the user'
        +" to correct that provider's settings on the Models page or in the deployment configuration, or to set"
        +' '+NAME+'.'+prefix+'BaseURL and '+NAME+'.'+prefix+'ApiKeyEnv so '+subject+' uses its own endpoint.')


def officialSource(ctx, capability):
    config = routeConfig(ctx, OFFICIAL)
    if config is None: return apiKeySource(ctx, DEEPSEEK_WEB_API_BASE_URL, 'DEEPSEEK_API_KEY')
    try: resolved = resolveApiKeyOptions(plainOptions(config), launch_environment_of(ctx))
    except Exception as error: return misconfigured(capability, OFFICIAL, error)
    return apiKeySource(ctx, toolsBase(resolved['baseURL']), resolved['apiKeyEnv'])


def accountSource(ctx, capability, config):
    try: base = resolveAccountOptions({} if config is None else plainOptions(config), launch_environment_of(ctx))['protocol']['baseURL']
    except Exception as error: return misconfigured(capability, ACCOUNT, error)
    return dict(kind='account', baseURL=toolsBase(base), resolveToken=lambda endpoint: resolveDeepSeekAccountToken(ctx, endpoint),
                rejectToken=lambda token: rejectDeepSeekAccountToken(ctx, token))


def ruleSources(ctx, capability, rule):
    account = routeConfig(ctx, ACCOUNT)
    if rule == 'account-conversation':
        return ([accountSource(ctx, capability, account)] if account is not None else [])+[officialSource(ctx, capability)]
    if rule in ('official-conversation', 'api-key'): return [officialSource(ctx, capability)]
    if rule == 'other-conversation': return [officialSource(ctx, capability), accountSource(ctx, capability, account)]
    if rule == 'account': return [accountSource(ctx, capability, account)]
    raise ValueError('web-deepseek-api: unexpected value '+str(rule))


def missingMessage(capability, rule, keyRef):
    subject = capability.title(); ref = stringify_json(keyRef)
    addKey = 'add the DeepSeek API key on the Models page or export '+ref+' in the launching environment'
    billing = NAME+'.'+capability+'Billing'; settings = 'on the Web search and fetch settings page'
    if rule == 'account-conversation':
        return ('DeepSeek '+subject+' API uses the DeepSeek account sign-in of this conversation, then the DeepSeek API key, and'
            +' neither is available: no signed-in DeepSeek account is available, and no key is configured for '+ref+'. Guide the'
            +' user to sign in to DeepSeek, or to '+addKey+'.')
    if rule == 'official-conversation':
        return ('DeepSeek '+subject+" API uses the DeepSeek API key, as this conversation's model provider does, and no key is"
            +' configured for '+ref+'. Guide the user to '+addKey+', or to sign in to DeepSeek and set '+billing+' to "account"'
            +' '+settings+'.')
    if rule == 'other-conversation':
        return ('DeepSeek '+subject+' API uses the DeepSeek API key, then the DeepSeek account sign-in, and neither is available:'
            +' no key is configured for '+ref+', and no signed-in DeepSeek account is available. Guide the user to '+addKey+', or'
            +' to sign in to DeepSeek.')
    if rule == 'account':
        return ('DeepSeek '+subject+' API bills only the signed-in DeepSeek account, and no signed-in DeepSeek account is'
            +' available. '+subject+' did not send the request. Guide the user to sign in to DeepSeek, or to set '+billing+' to'
            +' "api-key" or "auto" '+settings+'.')
    if rule == 'api-key':
        return ('DeepSeek '+subject+' API bills only the DeepSeek API key, and no key is configured for '+ref+'. Guide the user to'
            +' '+addKey+', or to set '+billing+' to "account" or "auto" '+settings+'.')
    raise ValueError('web-deepseek-api: unexpected value '+str(rule))


def resolveTarget(ctx, capability, own, llmProvider):
    guidance = dict(subject=capability.title(), plugin=NAME, custom=False,
                    baseURLField=capability+'BaseURL', apiKeyEnvField=capability+'ApiKeyEnv')
    base, ref = own.get('baseURL') or None, own.get('ref') or None
    if base is not None or ref is not None:
        ref = credential_ref(ref if ref is not None else 'DEEPSEEK_API_KEY'); quoted = stringify_json(ref)
        guidance['custom'] = True
        return dict(guidance=guidance, auth=dict(sources=[apiKeySource(ctx, base or DEEPSEEK_WEB_API_BASE_URL, ref)],
            missingCredentialMessage='DeepSeek '+capability.title()+' API sends the API key under '+quoted+' to its own endpoint, and no key is'
            +' configured for '+quoted+'. Guide the user to export '+quoted+' in the launching environment, or to correct'
            +' '+NAME+'.'+capability+'ApiKeyEnv.'))
    rule = own['billing'] if own['billing'] != 'auto' else 'account-conversation' if llmProvider == ACCOUNT else 'official-conversation' if llmProvider == OFFICIAL else 'other-conversation'
    sources = ruleSources(ctx, capability, rule)
    ref = next((source['key']['ref'] for source in sources if source['kind'] == 'api-key' and not isinstance(source['key'], str)), 'DEEPSEEK_API_KEY')
    return dict(guidance=guidance, auth=dict(sources=sources, missingCredentialMessage=missingMessage(capability, rule, ref)))


def latestUserQuestion(session):
    if session is None: return None
    message = next((message for message in reversed(session.deriveMessages()) if field(message, 'role') == 'user'
                    and field(field(message, 'source'), 'kind') == 'user'), None)
    if message is None: return None
    return '\n'.join(field(block, 'text') for block in field(message, 'content') if field(block, 'type') == 'text')


class CurrentWebDeepSeekApi(Plugin):
    id = NAME
    inject = ['web']
    Config = Config

    def apply(self, ctx):
        def value(key):
            from dsh.cordis.volatile import is_volatile
            item = self.config.get(key)
            item = item.get() if is_volatile(item) else item
            return None if item is _UNDEFINED else item
        def target(capability, provider):
            return resolveTarget(ctx, capability, dict(baseURL=value(capability+'BaseURL'), ref=value(capability+'ApiKeyEnv'),
                                                       billing=value(capability+'Billing')), provider)
        def session():
            agents = ctx.get('agents')
            agent = agents.currentInitiator() if agents is not None else None
            return field(agent, 'session')
        def current(capability):
            initiating = session()
            return target(capability, field(initiating.requestContext(), 'provider') if initiating is not None else None)
        def searchOptions():
            options = dict(current('search'), count=value('count'), requestsPerSecond=value('searchRequestsPerSecond'))
            if value('sendOriginalQuestion'): options['originalQuestion'] = lambda: latestUserQuestion(session())
            return options
        search = DeepSeekSearchApiProvider(searchOptions); fetch = DeepSeekFetchApiProvider(lambda: current('fetch'))
        async def ready(capability, provider):
            return await isDeepSeekWebAuthReady(target(capability, provider)['auth'], '/'+capability)
        searchRow = SimpleNamespace(id=search.id, description=search.description, available=search.available,
                                    ready=lambda provider=None: ready('search', provider), search=search.search)
        fetchRow = SimpleNamespace(id=fetch.id, description=fetch.description, available=fetch.available,
                                   ready=lambda provider=None: ready('fetch', provider), fetch=fetch.fetch)
        ctx.effect(lambda: ctx.web.registerSearchProvider(searchRow))
        ctx.effect(lambda: ctx.web.registerFetchProvider(fetchRow))
