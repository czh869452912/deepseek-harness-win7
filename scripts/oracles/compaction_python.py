"""Observe native compaction over the shared pinned-source recipes."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dsh.compaction.compaction_basic.config import resolve_config, resolve_target_policy, resolve_compact_spec
from dsh.compaction.engine import CompactionEngine, ManualCompactionError
from dsh.compaction.transaction import compact
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionPlugin
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.llm.token_meter import TokenMeter
from dsh.llm.llm_service import LLMService
from dsh.compaction.command_compact import CommandCompactPlugin
from dsh.interaction.commands import CommandsPlugin
from dsh.core.agent import Agent


async def command(spec):
    ctx = Context()
    try:
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(CommandsPlugin)
        session = ctx.get('sessions').create()
        agent = Agent(session, ctx=ctx)
        control, reason, calls = AbortController(), RuntimeError('operator cancelled'), []
        entered, close, closed, flush, flushed = [asyncio.Event() for _ in range(5)]
        class Backend:
            async def compact_now(self, owner, signal, identity):
                calls.append(dict(sameAgent=owner is agent, sameSignal=signal is control.signal,
                    sameCommand=identity == next(event for event in session.events if event['type'] == 'command/run')['data']['commandId']))
                if spec.get('action') == 'abort':
                    control.abort(reason)
                    raise ManualCompactionError('summary', 'late failure')
                if spec.get('action') == 'drain':
                    entered.set()
                    await close.wait()
                    closed.set()
                    await flush.wait()
                    flushed.set()
                    raise reason
                if spec.get('failure'):
                    raise reason if spec['failure'] == 'unexpected' else ManualCompactionError(spec['failure'], 'private detail')
                if spec.get('action') == 'no-history':
                    return None
                provenance = dict(compactionId='fixture', sourceCommandId=identity)
                session.append('compaction/start', dict(provenance, turn=None))
                summary = session.append('compaction/summary', dict(provenance, summary=[dict(type='text', text='summary')],
                    shadowedRange=dict(start=1, end=7), shadowedSeqs=[1, 3, 7], shadowedTokenCount=42, provider='test', model='model'))
                session.append('compaction/end', dict(provenance, turn=None))
                return dict(shadowedSeqs=[1, 3, 7], shadowedTokenCount=42, summarySeq=summary['seq'])
        ctx.set_service('compaction', Backend())
        plugin = await ctx.plugin(CommandCompactPlugin)
        if spec.get('action') == 'pre-aborted':
            control.abort(reason)
        async def observe_execution():
            try:
                result = await ctx.get('commands').execute(agent, '/compact' + spec.get('suffix', ''), [], control.signal)
                return dict(result=dict(result.result))
            except Exception as error:
                return dict(thrown=str(error), sameReason=error is reason)
        pending = asyncio.create_task(observe_execution())
        drain = None
        if spec.get('action') == 'drain':
            await entered.wait()
            control.abort(reason)
            await pending
            disposal = asyncio.ensure_future(plugin.dispose())
            for _ in range(50):
                if ctx.get('commands').find(agent, 'compact') is None:
                    break
                await asyncio.sleep(0)
            unregistered, waits_close = ctx.get('commands').find(agent, 'compact') is None, not disposal.done()
            close.set()
            await closed.wait()
            waits_flush = not disposal.done()
            flush.set()
            await flushed.wait()
            await disposal
            drain = dict(unregistered=unregistered, waitsClose=waits_close, waitsFlush=waits_flush, disposed=disposal.done())
        outcome = await pending
        events = []
        for event in session.events:
            data = dict(event['data'])
            for key in ('commandId', 'sourceCommandId'):
                if key in data:
                    data[key] = 'command'
            events.append(dict(type=event['type'], data=data))
        result = dict(mode=spec['mode'], outcome=outcome, calls=calls, surface=list(session.surface.nodes), events=events)
        if drain is not None:
            result['drain'] = drain
        return result
    finally:
        await ctx.fiber.dispose()


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


async def transaction(spec):
    from types import SimpleNamespace
    ctx = Context()
    try:
        await ctx.plugin(SessionPlugin)
        meter = TokenMeter(ctx)
        session = ctx.get('sessions').create()
        session.append_user_message('important facts ' * 300)
        session.append_user_message('recent question')
        session.append_request_header(dict(config=dict(provider='old', model='old-model'), system='original prefix'))
        manual = spec.get('manual', True)
        if not manual:
            session.append('turn/start', dict(turn=1))
        control, reason, inputs, flushed = AbortController(), RuntimeError('caller stopped'), [], []
        async def summarize(input, agent, signal):
            if spec.get('action') == 'header':
                session.append_request_header(dict(config=dict(provider='new', model='new-model'), system='changed prefix'))
            inputs.append(dict(keys=sorted(input), system=input.get('system'),
                text=[''.join(block.get('text', '') for block in message['content']) for message in input['messages']],
                routed=agent.session.request_header()['config'], sameSignal=signal is control.signal))
            if spec.get('action') == 'outside':
                session.append_user_message('outside span')
            if spec.get('action') == 'hook-error':
                raise ManualCompactionError('busy', 'hook failed')
            result = dict(summary=[dict(type='text', text='custom checkpoint')], provider='custom', model='template',
                rawOutput=[dict(type='text', text='raw')], compactionId='spoofed', sourceCommandId='spoofed',
                extra='private data')
            if spec['mode'] == 'transaction-private-fields':
                result['shadowedTokenCount'] = -1
            if 'marker' in spec:
                result['llmStreamCall'] = spec['marker']
            return result
        async def flush():
            flushed.append(True)
            if spec['flush'] == 'cancel':
                control.abort(reason)
            if spec['flush'] != 'void':
                raise RuntimeError('flush failed')
        try:
            result = await compact(SimpleNamespace(ctx=ctx, summarize=summarize), session, 0, 0,
                agent=Owner(session), manual=manual, source_command_id='real-command', signal=control.signal,
                flush=flush if 'flush' in spec else None)
            outcome = {key: result[key] for key in ('shadowedSeqs', 'shadowedTokenCount')}
        except Exception as error:
            outcome = dict(error=True, code=getattr(error, 'code', None), callerReason=error is reason)
        opening = next(event for event in session.events if event['type'] == 'compaction/start')
        summaries = []
        for event in session.events:
            if event['type'] == 'compaction/summary':
                body = {key: value for key, value in event['data'].items() if key != 'compactionId'}
                body['sameIdentity'] = event['data']['compactionId'] == opening['data']['compactionId']
                summaries.append(body)
        return dict(mode=spec['mode'], inputs=inputs, outcome=outcome, summaries=summaries, flushes=len(flushed),
            generation=session.surface.replace_generation, nodes=list(session.surface.nodes),
            events=[dict(type=event['type'], error='error' in event['data']) for event in session.events if event['type'].startswith('compaction/')])
    finally:
        await ctx.fiber.dispose()


async def observe():
    cases = json.loads((ROOT / 'scripts/oracles/compaction-cases.json').read_text(encoding='utf-8'))
    rows = []
    for spec in cases:
        if spec['kind'] == 'command':
            rows.append(await command(spec))
            continue
        if spec['kind'] == 'transaction':
            rows.append(await transaction(spec))
            continue
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
