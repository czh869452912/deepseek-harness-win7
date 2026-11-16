"""Shared DeepSeek credential lookup, independent of route-specific wire headers."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.environment import launch_environment_of
from dsh.llm.llm_service import assert_usable_api_key
from dsh.typert.stores import field


async def resolveDeepSeekApiKey(ctx, ref):
    credentials = ctx.get('credentials')
    if credentials is not None:
        hit = await await_callback_result(credentials.resolve(ref))
        return None if hit is None else assert_usable_api_key(field(hit,'value'),'llm-deepseek',ref)
    ambient = launch_environment_of(ctx).get(ref)
    value = field(ambient,'value')
    return None if value is None or len(value) == 0 else assert_usable_api_key(value,'llm-deepseek',ref)


async def deepSeekApiKeyConfigured(ctx, ref):
    credentials = ctx.get('credentials')
    if credentials is None:
        value = field(launch_environment_of(ctx).get(ref),'value')
        return value is not None and len(value) > 0
    return field(await await_callback_result(credentials.describe(ref)),'configured')


async def resolveDeepSeekAccountToken(ctx, endpoint):
    account = ctx.get('deepseekAccount')
    return None if account is None else await await_callback_result(account.resolveToken(endpoint))


async def rejectDeepSeekAccountToken(ctx, token):
    account = ctx.get('deepseekAccount')
    try:
        if account is not None: await await_callback_result(account.rejectToken(token))
    except Exception:
        # Account storage failure cannot replace the request's authentication failure.
        pass
