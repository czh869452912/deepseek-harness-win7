"""Actual split API-key plugin mounting, discovery and live credentials."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(mode=mode, key=key) for mode in ('configured', 'public', 'listing-fail', 'reload-ref', 'live-credential')
            for key in (None, '', ' valid-key ', 'bad\nkey')]


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.volatile import WRITE
    from dsh.llm import deepseek_provider_current as module
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.llm.model_listing import parseModelListing
    from dsh.llm.llm_service import LlmError
    rows = []; original = module.requestModelListing
    try:
        for index, case in enumerate(cases()):
            ctx = Context(); calls = []; listing = []; key = [case['key']]
            raw = {} if case['mode'] in ('public', 'listing-fail') else dict(models=[dict(id='configured-model')])
            config = module.CurrentDeepSeekApiKeyProvider.Config(raw)
            plugin = module.CurrentDeepSeekApiKeyProvider(config=config)
            async def resolve(ref):
                calls.append(ref)
                return None if key[0] is None or ref == 'OTHER_KEY' else dict(value=key[0])
            async def load(url, headers, signal):
                listing.append(dict(url=url, headers=headers))
                if case['mode'] == 'listing-fail': raise LlmError('could not reach '+url, 'TRANSPORT')
                return parseModelListing(dict(data=[dict(id='deepseek-v4.1', api_capabilities=dict(anthropic_messages={}))]))
            module.requestModelListing = load
            ctx.set_service('credentials', SimpleNamespace(resolve=resolve))
            try:
                await ctx.plugin(CurrentLlmRuntime)
                def mount(child): return plugin.apply(child)
                mount.inject = ['llm']
                await ctx.plugin(mount)
                llm = ctx.llm
                async def discover():
                    try: return dict(models=await llm.list_models('deepseek-official'))
                    except Exception as error: return dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
                results = [await discover()]
                if case['mode'] == 'reload-ref':
                    getattr(config['apiKeyEnv'], WRITE)('OTHER_KEY'); ctx.emit('loader/volatile-update'); results.append(await discover())
                if case['mode'] == 'live-credential': key[0] = None; results.append(await discover())
                directories = [{key: row[key] for key in ('provider', 'displayName', 'settingsNs', 'settingsPath')} for row in llm.listConfigurableProviders()]
                row = dict(index=index, results=results, calls=calls, listings=listing, providers=llm.list_providers(), directory=directories)
            finally: await ctx.fiber.dispose()
            row['afterDispose'] = dict(providers=llm.list_providers(), directory=llm.listConfigurableProviders())
            rows.append(row)
        return rows
    finally: module.requestModelListing = original


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_api_key_provider.mts', 'Actual API-key plugin over LLM services: discovery, live keys, listing/fallback and reversible registration.',
        [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_provider_current.py'], prepare=prepare)
