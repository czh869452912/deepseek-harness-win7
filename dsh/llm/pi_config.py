"""Detached route generations for the multi-provider adapter."""
import copy
import math

from dsh.llm.pi_catalog import resolve_route_models
from dsh.llm.retry_policy import MAX_TIMER_DELAY_MS, resolve_retry_policy

PROTOCOLS = ('openai-completions', 'openai-responses', 'anthropic-messages')
DEFAULTS = dict(defaultContextWindow=262144, defaultMaxTokens=32768, defaultInput=['text'],
                streamIdleTimeoutMs=300000, maxRequestImageBytes=20 * 1024 * 1024,
                requestImagePixelBudget=2048 * 2048, requestImageMaxBytes=1024 * 1024)


def resolve_profiles(providers=None):
    if providers is None:
        return {}
    if not isinstance(providers, dict):
        raise ValueError('llm-pi-ai: providers must be a route-keyed dictionary')
    resolved = {}
    for provider, source in providers.items():
        if not isinstance(provider, str) or not provider or not isinstance(source, dict):
            raise ValueError('llm-pi-ai: route names must be non-empty and profiles must be objects')
        if {'provider', 'maxRetries', 'maxRetryDelayMs'} & source.keys():
            raise ValueError('llm-pi-ai: removed provider/retry configuration fields')
        for field in ('baseURL', 'displayName'):
            if field in source and (not isinstance(source[field], str) or not source[field]):
                raise ValueError('llm-pi-ai: {} must be a non-empty string'.format(field))
        if 'api' in source and source['api'] not in PROTOCOLS:
            raise ValueError('llm-pi-ai: unsupported explicit protocol')
        profile = dict(copy.deepcopy(DEFAULTS), **copy.deepcopy(source))
        if 'apiKeyEnv' in profile:
            from dsh.credentials.credentials import credential_ref
            profile['apiKeyEnv'] = credential_ref(profile['apiKeyEnv'])
        idle = profile['streamIdleTimeoutMs']
        if type(idle) not in (int, float) or not math.isfinite(idle) or not 0 < idle <= MAX_TIMER_DELAY_MS:
            raise ValueError('llm-pi-ai: invalid streamIdleTimeoutMs')
        for field in ('maxRequestImageBytes', 'requestImagePixelBudget', 'requestImageMaxBytes'):
            value = profile[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or not float(value).is_integer():
                raise ValueError('llm-pi-ai: {} must be a positive integer'.format(field))
            if field != 'maxRequestImageBytes' and value > 9007199254740991:
                raise ValueError('llm-pi-ai: {} must be a safe integer'.format(field))
        if not profile['defaultInput']:
            raise ValueError('llm-pi-ai: defaultInput must name at least one modality')
        catalog = resolve_route_models(dict(profile, provider=provider))
        profile.update(provider=provider, displayName=source.get('displayName', provider),
                       retryPolicy=resolve_retry_policy(source.get('retryPolicy')), **catalog)
        resolved[provider] = profile
    return resolved
