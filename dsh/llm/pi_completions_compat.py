"""Protocol compatibility detection adapted from pi-ai 0.84.2."""


def get_compat(model):
    provider, url = model['provider'], model['baseUrl']
    zai = provider in ('zai', 'zai-coding-cn') or 'api.z.ai' in url or 'open.bigmodel.cn' in url
    together = provider == 'together' or 'api.together.ai' in url or 'api.together.xyz' in url
    moonshot = provider in ('moonshotai', 'moonshotai-cn') or 'api.moonshot.' in url
    router = provider == 'openrouter' or 'openrouter.ai' in url
    workers = provider == 'cloudflare-workers-ai' or 'api.cloudflare.com' in url
    gateway = provider == 'cloudflare-ai-gateway' or 'gateway.ai.cloudflare.com' in url
    nvidia = provider == 'nvidia' or 'integrate.api.nvidia.com' in url
    ant = provider == 'ant-ling' or 'api.ant-ling.com' in url
    deepseek = provider == 'deepseek' or 'deepseek.com' in url.lower()
    grok = provider == 'xai' or 'api.x.ai' in url
    nonstandard = any((nvidia, provider == 'cerebras', 'cerebras.ai' in url, grok, together,
                      'chutes.ai' in url, deepseek, zai, moonshot, provider == 'opencode',
                      'opencode.ai' in url, workers, gateway, ant))
    max_tokens = any(('chutes.ai' in url, deepseek, moonshot, gateway, together, nvidia, ant, zai))
    result = dict(supportsStore=not nonstandard,
        supportsDeveloperRole=(router and model['id'].startswith(('anthropic/', 'openai/'))) or (not nonstandard and not router),
        supportsReasoningEffort=not any((grok, zai, moonshot, together, gateway, nvidia, ant)),
        supportsUsageInStreaming=True, supportsFinishReason=True,
        maxTokensField='max_tokens' if max_tokens else 'max_completion_tokens',
        requiresToolResultName=False, requiresAssistantAfterToolResult=False, requiresThinkingAsText=False,
        requiresReasoningContentOnAssistantMessages=deepseek,
        thinkingFormat='deepseek' if deepseek else 'zai' if zai else 'together' if together else 'ant-ling' if ant else 'openrouter' if router else 'openai',
        openRouterRouting={}, vercelGatewayRouting={}, chatTemplateKwargs={}, chatTemplateArgs={},
        zaiToolStream=False, supportsThinkingTokenBudget=False,
        supportsStrictMode=not any((moonshot, together, gateway, nvidia)), supportsOpenAIGrammarTools=False,
        sendSessionAffinityHeaders=False, sessionAffinityFormat='openrouter' if router else 'openai',
        supportsLongCacheRetention=not any((together, workers, gateway, nvidia, ant)))
    if provider == 'openrouter' and model['id'].startswith('anthropic/'):
        result['cacheControlFormat'] = 'anthropic'
    for key, value in model.get('compat', {}).items():
        if value is not None:
            result[key] = value
    return result
