"""Settings-owned DeepSeek native search plugin, using the canonical web seam."""
import inspect

from dsh.cordis.environment import launch_environment_of
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.credentials.credentials import credential_ref
from dsh.settings.provider import install_settings_section
from dsh.settings.types import settings_namespace
from dsh.web.deepseek_search_provider import (
    DeepSeekSearchProvider, DEEPSEEK_PROVIDER_ID, DEEPSEEK_DEFAULT_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_DEFAULT_API_VERSION,
    DEEPSEEK_DEFAULT_MAX_TOKENS, DEEPSEEK_DEFAULT_MAX_USES,
)

WEB_SEARCH_DEEPSEEK_SETTINGS_NAMESPACE = settings_namespace('web-search-deepseek')
Config = z.object({
    'apiKey': z.string().role('secret'),
    'apiKeyEnv': z.string().role('credential-ref').default('DEEPSEEK_API_KEY'),
    'baseURL': z.string(),
    'model': z.string().default(DEEPSEEK_DEFAULT_MODEL),
    'apiVersion': z.string().default(DEEPSEEK_DEFAULT_API_VERSION),
    'maxTokens': z.number().step(1).min(1).default(DEEPSEEK_DEFAULT_MAX_TOKENS),
    'maxUses': z.number().step(1).min(1).default(DEEPSEEK_DEFAULT_MAX_USES),
})


def resolve_options(ctx, config):
    ref = credential_ref(config.get('apiKeyEnv', 'DEEPSEEK_API_KEY'))

    async def resolve_key():
        credentials = ctx.get('credentials')
        if credentials is not None:
            result = credentials.resolve(ref)
            result = await result if inspect.isawaitable(result) else result
        else:
            result = launch_environment_of(ctx).get(ref)
        value = result.get('value') if isinstance(result, dict) else getattr(result, 'value', None)
        return value if value is not None and len(value) > 0 else None

    def record_request(request):
        agents = ctx.get('agents')
        agent = agents.currentInitiator() if agents is not None else None
        if agent is not None:
            agent.session.append('web/deepseek-search-llm-request', request)

    base = launch_environment_of(ctx).get('DEEPSEEK_SEARCH_BASE_URL')
    return dict(apiKey=config.get('apiKey') or None, apiKeyEnv=ref, resolveApiKey=resolve_key,
                baseURL=config.get('baseURL', getattr(base, 'value', DEEPSEEK_DEFAULT_BASE_URL)),
                model=config.get('model', DEEPSEEK_DEFAULT_MODEL),
                apiVersion=config.get('apiVersion', DEEPSEEK_DEFAULT_API_VERSION),
                maxTokens=config.get('maxTokens', DEEPSEEK_DEFAULT_MAX_TOKENS),
                maxUses=config.get('maxUses', DEEPSEEK_DEFAULT_MAX_USES), recordRequest=record_request)


class WebSearchDeepSeekPlugin(Plugin):
    id = 'web-search-deepseek'
    name = '@deepseek-ai/dsh-web-search-deepseek'
    inject = ['web']
    Config = Config

    def apply(self, ctx):
        self.current = lambda: self.config
        install_settings_section(ctx, WEB_SEARCH_DEEPSEEK_SETTINGS_NAMESPACE, Config, self.config,
                                 {'setSource': lambda source: setattr(self, 'current', source), 'onChange': lambda: None})
        ctx.get('web').registerSearchProvider(DeepSeekSearchProvider(lambda: resolve_options(ctx, self.current())))
