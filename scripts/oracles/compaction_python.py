"""Observe native compaction over the shared pinned-source recipes."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dsh.compaction.compaction_basic.config import resolve_config, resolve_target_policy, resolve_compact_spec
from dsh.compaction.engine import CompactionEngine
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionPlugin
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.llm.token_meter import TokenMeter
from dsh.llm.llm_service import LLMService


class Llm:
    def __init__(self, spec):
        self.window = 1000 if spec.get('window', 1000) == 'measured' else spec.get('window', 1000)
        self.spec, self.requests, self.resolutions = spec, [], []

    async def resolve_model(self, provider, model, signal=None):
        self.resolutions.append(dict(provider=provider, model=model))
        result = dict(provider=provider, id=model, name=model)
        if self.window is not None:
            result['context'] = dict(contextWindow=self.window)
        return result

    async def prepare_call(self, provider, model, signal=None):
        return dict(model=await self.resolve_model(provider, model, signal), stream=self.stream)

    async def stream(self, request):
        self.requests.append(dict(provider=request['provider'], model=request['model'], maxTokens=request['maxTokens'],
            system=request.get('system'), tools=request.get('tools'),
            text='\n'.join(''.join(block.get('text', '') for block in message['content']) for message in request['messages'])))
        text = 'long first checkpoint ' * 5 if self.spec.get('decreasingSummary') and len(self.requests) == 1 else 'small checkpoint'
        yield dict(type='text-delta', index=0, text=text)
        yield dict(type='finish', reason=dict(kind='stop'))


class Owner:
    def __init__(self, session):
        from types import SimpleNamespace
        self.session = session
        self.options = SimpleNamespace(provider='fallback', model='fallback')


async def observe():
    cases = json.loads((ROOT / 'scripts/oracles/compaction-cases.json').read_text(encoding='utf-8'))
    rows = []
    for spec in cases:
        if spec['kind'] == 'config':
            try:
                config = resolve_config(spec['config'])
                if 'target' not in spec:
                    rows.append(dict(mode=spec['mode'], config=config, frozen=isinstance(config, FrozenDict)))
                    continue
                policy = resolve_target_policy(config, spec['target'])
                compact = resolve_compact_spec(policy, spec['window'])
                rows.append(dict(mode=spec['mode'], config=config, policy=policy, compact=compact,
                    frozen=isinstance(config, FrozenDict) and isinstance(config['modelPolicies'], FrozenList) and isinstance(compact['target'], FrozenDict)))
            except ValueError as error:
                rows.append(dict(mode=spec['mode'], error=True, targetKey=getattr(error, 'target_key', None), message=str(error)))
            continue
        ctx = Context()
        try:
            await ctx.plugin(SessionPlugin)
            llm = Llm(spec)
            runtime = LLMService(ctx)
            ctx.set_service('llm', runtime)
            runtime.register_adapter(['routed', 'summary-p'], llm)
            meter = TokenMeter(ctx)
            session = ctx.get('sessions').create()
            for turn in range(1, 5):
                text = 'fixture ' * 40
                session.append('turn/start', dict(turn=turn))
                session.append_user_message(text + ' user ' + str(turn))
                session.append('step/start', dict(turn=turn, step=1))
                if turn == 1 and not spec.get('headerless'):
                    header = dict(config=dict(provider='routed', model='shared'))
                    if 'systemChars' in spec:
                        header['system'] = 'x' * spec['systemChars']
                    session.append('request/header', dict(header=header, reason='initial'))
                session.append_assistant_message(dict(role='assistant', content=[dict(type='text', text=text + ' assistant ' + str(turn))]), turn=turn, step=1)
                session.append('step/end', dict(turn=turn, step=1))
                session.append('turn/end', dict(turn=turn, reason=dict(kind='completed')))
            session.append('turn/start', dict(turn=5))
            if spec.get('window') == 'measured':
                llm.window = meter.measure(session)['totalTokens']
            engine, owner, controller = CompactionEngine(ctx=ctx, config=spec['config']), Owner(session), AbortController()
            if spec.get('aborted'):
                controller.abort('stop')
            outcomes = []
            for action in spec.get('actions', [spec.get('trigger', 'pressure')]):
                try:
                    if action == 'overflow':
                        result = await ctx.waterfall('agent/request-error', dict(agent=owner, failure=dict(code='CONTEXT_WINDOW_EXCEEDED', message='overflow'), signal=controller.signal), lambda *_: 'delegate')
                    elif action == 'pre-step':
                        result = await ctx.waterfall('agent/pre-step', dict(agent=owner, signal=controller.signal), lambda *_: 'delegate')
                    else:
                        result = await engine.compact_if_needed(owner, action, controller.signal)
                    outcomes.append(result if result is None or result == 'delegate' or result.get('kind') == 'retry'
                        else {key: result[key] for key in ('shadowedRange', 'shadowedSeqs', 'shadowedTokenCount')})
                except (ValueError, RuntimeError) as error:
                    outcomes.append(dict(error=True, targetKey=getattr(error, 'target_key', None)))
            rows.append(dict(mode=spec['mode'], outcomes=outcomes, requests=llm.requests, resolutions=llm.resolutions,
                generation=session.surface.replace_generation, measurement=meter.measure(session),
                compactionEvents=[dict(type=e['type'], seq=e['seq']) for e in session.events if e['type'].startswith('compaction/')]))
        finally:
            await ctx.fiber.dispose()
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(observe())
