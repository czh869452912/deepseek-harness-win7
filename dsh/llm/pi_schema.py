"""Editable pi-ai settings metadata matching the pinned configuration vocabulary."""
from dsh.cordis.schema import Schema as z
from dsh.llm.pi_catalog import OFFERED, THINKING_LEVELS
from dsh.llm.pi_config import DEFAULTS, PROTOCOLS
from dsh.llm.retry_policy import DEFAULT_CODES, MAX_TIMER_DELAY_MS


def config_schema():
    positive = lambda: z.number().step(1).min(1)
    variable = z.union([z.string(), z.number(), z.boolean(), z.const_(None),
        z.object({'$var': z.union(['thinking.enabled', 'thinking.effort']).required(), 'omitWhenOff': z.boolean()})])
    compat_fields = {key: z.boolean() for key in OFFERED}
    compat_fields.update(maxTokensField=z.union(['max_completion_tokens', 'max_tokens']),
        thinkingFormat=z.union(['openai', 'deepseek', 'openrouter', 'together', 'baseten', 'zai', 'qwen',
                                'chat-template', 'qwen-chat-template', 'string-thinking', 'ant-ling']),
        chatTemplateKwargs=z.dict(variable), chatTemplateArgs=z.dict(variable), cacheControlFormat=z.const_('anthropic'))
    compat = z.object(compat_fields)
    fields = dict(name=z.string(), contextWindow=positive(), maxTokens=positive(),
                  input=z.array(z.union(['text', 'image'])), compat=compat,
                  reasoningEfforts=z.union([z.const_(False), z.dict(z.union([z.string(), z.const_(None)]), z.union(list(THINKING_LEVELS)))]))
    model = z.object(dict(fields, id=z.string().required()))
    backoff = z.object(dict(initialDelayMs=z.number().max(MAX_TIMER_DELAY_MS).default(500),
                           maxDelayMs=z.number().max(MAX_TIMER_DELAY_MS).default(10000),
                           jitterRatio=z.number().min(0).max(1).default(.1)))
    retry = z.union([z.object(dict(mode=z.const_('normal').required(),
                    maxRetries=z.number().step(1).min(0).max(9007199254740991).default(5),
                    retryableCodes=z.array(z.string()).default(DEFAULT_CODES), backoff=backoff)),
                    z.object(dict(mode=z.const_('always').required(), backoff=backoff))])
    profile = dict(apiKeyEnv=z.string().role('credential-ref'), displayName=z.string(),
        api=z.union(list(PROTOCOLS)), baseURL=z.string(), models=z.array(model), modelOverrides=z.dict(z.object(fields)),
        compat=compat, headers=z.dict(z.string()), reasoning=z.union(list(THINKING_LEVELS)),
        thinkingBudgets=z.object({level: z.number() for level in ('minimal', 'low', 'medium', 'high')}),
        cacheRetention=z.union(['none', 'short', 'long']), transport=z.union(['sse', 'websocket', 'websocket-cached', 'auto']),
        timeoutMs=z.natural(), websocketConnectTimeoutMs=z.natural(), retryPolicy=retry)
    for key, value in DEFAULTS.items():
        if key == 'defaultInput':
            profile[key] = z.array(z.union(['text', 'image'])).default(value)
        elif key == 'streamIdleTimeoutMs':
            profile[key] = z.number().min(float.fromhex('0x0.0000000000001p-1022')).max(MAX_TIMER_DELAY_MS).default(value)
        else:
            profile[key] = positive().default(value)
    return z.object(dict(providers=z.dict(z.object(profile)).default({})))
