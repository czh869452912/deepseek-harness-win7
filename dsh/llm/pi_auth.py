"""Explicit credentials never fall back to another tenant's ambient key."""
import inspect

from dsh.cordis.environment import launch_environment_of
from dsh.llm.llm_service import LlmError, assert_usable_api_key
from dsh.credentials.credentials import credential_key, is_credential_key_segment

# pi-ai 0.84.2 envApiKeyAuth declarations. OAuth and cloud-native auth are not
# inferred from a provider name; those require their own protocol/auth port.
ENV_KEYS = dict(ant_ling='ANT_LING_API_KEY', baseten='BASETEN_API_KEY', cerebras='CEREBRAS_API_KEY',
    deepseek='DEEPSEEK_API_KEY', fireworks='FIREWORKS_API_KEY', github_copilot='COPILOT_GITHUB_TOKEN',
    groq='GROQ_API_KEY', huggingface='HF_TOKEN', mistral='MISTRAL_API_KEY', moonshotai='MOONSHOT_API_KEY',
    moonshotai_cn='MOONSHOT_API_KEY', nvidia='NVIDIA_API_KEY', openai='OPENAI_API_KEY',
    opencode='OPENCODE_API_KEY', opencode_go='OPENCODE_API_KEY', openrouter='OPENROUTER_API_KEY',
    qwen_token_plan='QWEN_TOKEN_PLAN_API_KEY', qwen_token_plan_individual='QWEN_TOKEN_PLAN_API_KEY',
    qwen_token_plan_cn='QWEN_TOKEN_PLAN_CN_API_KEY', zai='ZAI_API_KEY', zai_coding_cn='ZAI_CODING_CN_API_KEY',
    xiaomi='XIAOMI_API_KEY', xiaomi_token_plan_sgp='XIAOMI_TOKEN_PLAN_SGP_API_KEY',
    xiaomi_token_plan_cn='XIAOMI_TOKEN_PLAN_CN_API_KEY', xiaomi_token_plan_ams='XIAOMI_TOKEN_PLAN_AMS_API_KEY',
    xai='XAI_API_KEY', vercel_ai_gateway='AI_GATEWAY_API_KEY', together='TOGETHER_API_KEY', radius='RADIUS_API_KEY')
ENV_KEYS = {key.replace('_', '-'): value for key, value in ENV_KEYS.items()}
ENV_KEYS.update(anthropic='ANTHROPIC_API_KEY', **{'kimi-coding': 'KIMI_API_KEY'})


def _value(hit):
    return hit.get('value') if isinstance(hit, dict) else getattr(hit, 'value', None)


async def _await(value):
    return await value if inspect.isawaitable(value) else value


async def ambient_value(ctx, name):
    credentials = ctx.get('credentials')
    if credentials is not None:
        hit = await _await(credentials.resolve(name))
        if hit is not None:
            return _value(hit)
    return _value(launch_environment_of(ctx).get(name))


async def resolve_api_key(ctx, provider, profile, ambient=True):
    ref = profile.get('apiKeyEnv')
    environment = launch_environment_of(ctx)
    if ref is not None:
        credentials = ctx.get('credentials')
        hit = credentials.resolve(ref) if credentials is not None else environment.get(ref)
        if inspect.isawaitable(hit):
            hit = await hit
        value = _value(hit)
        if not value:
            raise LlmError('llm-pi-ai: no credential for provider route "{}"; configure {}'.format(provider, ref), 'MISSING_CREDENTIAL')
        return assert_usable_api_key(value, 'llm-pi-ai', ref)
    if not ambient:
        return None
    credentials = ctx.get('credentials')
    if credentials is not None and is_credential_key_segment(provider):
        reader = getattr(credentials, 'readRecord', None)
        record = await _await(reader(credential_key('llm-pi-ai', provider))) if reader else None
        if record is not None:
            if record.get('kind') != 'api-key':
                raise LlmError('stored grant for "{}" requires an unimplemented OAuth handler'.format(provider), 'UNSUPPORTED_AUTH')
            if record.get('key'):
                return assert_usable_api_key(record['key'], 'llm-pi-ai', provider)
    if ambient and provider in ENV_KEYS:
        ref = ENV_KEYS[provider]
        value = await ambient_value(ctx, ref)
        if value:
            return assert_usable_api_key(value, 'llm-pi-ai', ref)
    return None
