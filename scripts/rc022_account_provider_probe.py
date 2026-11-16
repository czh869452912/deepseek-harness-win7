"""Actual account provider catalog and request-error mapping contracts."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(mode=mode, token=token) for mode in ('normal', 'missing-service', 'resolve-fail', 'listing-fail',
            'unknown-override', 'known-override', 'reject-fail') for token in (None, 'account-token')]


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.llm import deepseek_provider_current as module
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.llm.model_listing import parseModelListing
    from dsh.llm.llm_service import LlmError
    rows = []; original = module.requestModelListing
    try:
        for index, case in enumerate(cases()):
            ctx = Context(); calls = []; listings = []
            raw = dict(baseURL='https://api.deepseek.com')
            if case['mode'] == 'unknown-override': raw['modelOverrides'] = {'not-listed': dict(name='Unknown')}
            if case['mode'] == 'known-override': raw['modelOverrides'] = {'deepseek-v4.1': dict(name='Friendly', maxTokens=64)}
            config = module.CurrentDeepSeekAccountProvider.Config(raw)
            plugin = module.CurrentDeepSeekAccountProvider(config=config)
            async def resolve(endpoint):
                calls.append(dict(resolve=endpoint))
                if case['mode'] == 'resolve-fail': raise RuntimeError('account offline')
                return case['token']
            async def reject(token):
                calls.append(dict(reject=token))
                if case['mode'] == 'reject-fail': raise RuntimeError('storage offline')
            async def load(url, headers, signal):
                listings.append(dict(url=url, headers=headers))
                if case['mode'] == 'listing-fail': raise LlmError('could not reach '+url, 'TRANSPORT')
                return parseModelListing(dict(data=[dict(id='deepseek-v4.1', api_capabilities=dict(anthropic_messages={}))]))
            module.requestModelListing = load
            if case['mode'] != 'missing-service': ctx.set_service('deepseekAccount', SimpleNamespace(resolveToken=resolve, rejectToken=reject))
            try:
                await ctx.plugin(CurrentLlmRuntime)
                def mount(child): return plugin.apply(child)
                mount.inject = ['llm']; await ctx.plugin(mount)
                llm = ctx.llm
                try: discovered = dict(models=await llm.list_models('deepseek-account'))
                except Exception as error: discovered = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
                mapped = []
                try:
                    dependencies = plugin.adapter.dependencies
                    auth = await dependencies['resolveAuth'](dependencies['options']())
                    for message, code, status in [('quota', 'QUOTA', 402), ('expired', 'AUTH', 401), ('denied', 'AUTH', 403), ('busy', 'SERVER', 503)]:
                        error = LlmError(message, code, status=status, providerRetryAfterMs=3, requestId='request')
                        result = await auth['onRequestError'](error)
                        mapped.append(dict(failure=result.failure, same=result is error, causeSame=getattr(result, 'cause', None) is error))
                    error = RuntimeError('other'); result = await auth['onRequestError'](error)
                    mapped.append(dict(otherSame=result is error))
                    auth_result = dict(headers=auth['headers'], mapped=mapped)
                except Exception as error: auth_result = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
                directory = [{key: row[key] for key in ('provider', 'displayName', 'settingsNs', 'settingsPath', 'error') if key in row} for row in llm.listConfigurableProviders()]
                row = dict(index=index, discovered=discovered, auth=auth_result, calls=calls, listings=listings, directory=directory, providers=llm.list_providers())
            finally: await ctx.fiber.dispose()
            row['afterDispose'] = dict(providers=llm.list_providers(), directory=llm.listConfigurableProviders()); rows.append(row)
        return rows
    finally: module.requestModelListing = original


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_provider.mts', 'Actual account provider catalog, directory diagnostics, auth headers and request-error mapping.',
        [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_provider_current.py'], prepare=prepare)
