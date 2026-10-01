"""Observe the actual native pruner; recipes are shared with the source runner."""
import asyncio
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.compaction.pruner import ToolResultPruner, ToolResultPrunerPlugin, DEFAULTS, PRUNE_MARKER, code_point_length, resolve_config
from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.session import Session, SessionPlugin
from dsh.core.session.invariant import SessionInvariantPlugin
from dsh.core.session.json import FrozenDict
from dsh.diagnostics.invariants import InvariantRegistry
from dsh.llm.token_meter import TokenMeter, TokenMeterPlugin

SMALL = dict(thresholdChars=50, headChars=4, tailChars=3)


def blocks(recipe):
    text = lambda value, **extra: dict(type='text', text=value, **extra)
    if recipe == 'short':
        return [text('a😀b'), dict(type='reasoning', text='unmeasured')]
    if recipe == 'threshold':
        return [text('x' * 50)]
    if recipe in ('astral', 'pairs', 'isolated', 'combining'):
        return [text({'astral': '😀', 'pairs': '\ud83d\ude00', 'isolated': '\ud83dX\ude00', 'combining': 'e\u0301'}[recipe] * 60, extra=dict(retain=True))]
    if recipe == 'nontext':
        return [dict(type='reasoning', text='x' * 200), dict(type='image', data='rich')]
    if recipe == 'empty':
        return [text(''), text('A' * 4), text(''), text('B' * 60), text(''), text('C' * 3), text('')]
    if recipe == 'zero':
        return [text('x' * 100)]
    if recipe == 'rich':
        return [text('A' * 40, label='first'), dict(type='reasoning', text='private-rich'), text('B' * 30),
            dict(type='tool-call', id='nested', name='nested', arguments='{}'), text('C' * 30, label='last')]
    raise ValueError(recipe)


def append_step(session, turn, call, content, extra=None):
    session.append('turn/start', dict(turn=turn))
    session.append('step/start', dict(turn=turn, step=1))
    assistant = dict(id='assistant-' + call, role='assistant', source=dict(kind='model', provider='test', model='model'),
        content=[dict(type='tool-call', id=call, name='bash', arguments='{}')])
    session.append('assistant/message', dict(turn=turn, step=1, message=assistant), surface_op='append')
    session.append('tool/call', dict(turn=turn, step=1, callId=call, name='bash', arguments='{}'))
    message = dict(id='result-' + call, role='user', source=dict(kind='tool', callId=call),
        content=[dict(type='tool-result', toolCallId=call, isError=True, content=content, futureBlock=dict(keep=True))],
        futureMessage=dict(keep=True))
    event = session.append('tool/result', dict(turn=turn, step=1, message=message, **(extra or {})), surface_op='append')
    session.append('step/end', dict(turn=turn, step=1))
    session.append('turn/end', dict(turn=turn, reason=dict(kind='completed')))
    return event['seq']


def wire(value):
    # JS strings expose UTF-16 storage; native explicit pairs and astral scalars
    # have the same wire value. Isolated surrogates are preserved, not replaced.
    if isinstance(value, str):
        return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'surrogatepass')
    if isinstance(value, list):
        return [wire(item) for item in value]
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    return value


async def loader_observation(ctx, spec):
    if spec['recipe'] == 'stale':
        await ctx.plugin(TokenMeterPlugin)
        try:
            await ctx.plugin(ToolResultPrunerPlugin, spec.get('config', dict(maxChars=100)))
            return dict(mode=spec['mode'], error=None)
        except Exception as error:
            return dict(mode=spec['mode'], error=str(error))
    if spec['recipe'] == 'lifecycle':
        fiber = await ctx.plugin(ToolResultPrunerPlugin, SMALL)
        pending = ctx.get('toolResultPruner') is None
        meter = await ctx.plugin(TokenMeterPlugin)
        first = ctx.get('toolResultPruner')
        await meter.dispose()
        retired = ctx.get('toolResultPruner') is None
        await ctx.plugin(TokenMeterPlugin)
        current = ctx.get('toolResultPruner')
        reload = current is not None and current is not first
        config = current.config
        await fiber.dispose()
        return dict(mode=spec['mode'], pending=pending, retired=retired, reload=reload, config=config,
            unloaded=ctx.get('toolResultPruner') is None)
    with TemporaryDirectory(prefix='pruner-loader-') as root:
        path = Path(root) / 'cordis.yml'
        path.write_text("- name: '@deepseek-ai/dsh-token-meter'\n"
                        "- name: '@deepseek-ai/dsh-compaction-tool-result-pruner'\n"
                        '  config:\n    thresholdChars: 100\n    headChars: 20\n    tailChars: 10\n', encoding='utf-8')
        ctx.baseUrl = Path(root).as_uri() + '/'
        try:
            await ctx.plugin(Loader)
            loader = ctx.get('loader')
            install_harness_plugin_classes(loader)
            await loader.create(dict(name='cordis:include', config=dict(path=path.as_uri())))
            await loader.await_tasks()
            service = ctx.get('toolResultPruner')
            config, loaded = service.config, isinstance(service, ToolResultPruner)
            await loader.root.update([])
            schema = ToolResultPruner.Config
            metadata = dict(type=schema.type, meta=schema.meta,
                fields=[dict(key=key, type=value.type, meta=value.meta) for key, value in schema.dict.items()])
            return dict(mode=spec['mode'], config=config, loaded=loaded, unloaded=ctx.get('toolResultPruner') is None, schema=metadata)
        finally:
            await ctx.fiber.dispose()


async def observe(spec):
    ctx = Context()
    try:
        if spec['kind'] == 'loader':
            return await loader_observation(ctx, spec)
        if spec['kind'] == 'config':
            raw = dict(spec['config'])
            try:
                config = resolve_config(raw)
                raw['headChars'] = 1
                return dict(mode=spec['mode'], config=config, frozen=isinstance(config, FrozenDict),
                    defaults=DEFAULTS, defaultsFrozen=isinstance(DEFAULTS, FrozenDict),
                    negativeZero=[key for key, value in config.items() if value == 0 and math.copysign(1, value) < 0])
            except Exception as error:
                return dict(mode=spec['mode'], error=str(error))
        if spec.get('recipe') == 'invariants':
            await ctx.plugin(SessionPlugin)
            await ctx.plugin(InvariantRegistry)
            await ctx.plugin(SessionInvariantPlugin)
        meter = TokenMeter(ctx)
        config = spec.get('config', dict(thresholdChars=code_point_length(PRUNE_MARKER), headChars=0, tailChars=0)
                          if spec['recipe'] == 'zero' else SMALL)
        pruner = ToolResultPruner(ctx=ctx, config=config)
        if spec['kind'] == 'content':
            original = blocks(spec['recipe'])
            result = pruner.prune_content(original)
            return wire(dict(mode=spec['mode'], before=pruner.measure_content(original), result=result,
                after=None if result is None else pruner.measure_content(result),
                richIdentity=result is None or all(any(item is block for item in result)
                    for block in original if block['type'] != 'text'), original=original))
        session = ctx.get('sessions').create('probe') if spec['recipe'] == 'invariants' else Session.create('probe')
        first = append_step(session, 1, 'a', blocks('rich') if spec['recipe'] == 'preserve' else [dict(type='text', text='A' * 100)],
            dict(isError=True, error=dict(name='ExitError', code='EXIT_1'), meta=dict(diff=['a', 'b']), futureField=dict(nested=True)))
        second = None
        if spec['recipe'] not in ('preserve', 'invariants'):
            append_step(session, 2, 'b', [dict(type='text', text='short')])
            second = append_step(session, 3, 'c', [dict(type='text', text='C' * 80)])
        rejection = None
        if spec['recipe'] == 'invariants':
            before = meter.measure(session)['totalTokens']
            try:
                pruner.prune_session(session)
            except Exception as error:
                rejection = dict(error=str(error), addedEvents=len(session.events) - 7,
                    beforeTokens=before, afterTokens=meter.measure(session)['totalTokens'], generation=session.surface.replace_generation)
        session.append('turn/start', dict(turn=2 if second is None else 4))
        original_append = session.append
        state = dict(replacements=0)
        def intercept(event_type, data, **options):
            if event_type == 'tool/result' and options.get('surface_op', {}).get('op') == 'replace':
                state['replacements'] += 1
                if state['replacements'] == 2 and spec['recipe'] == 'partial':
                    raise RuntimeError('second replacement rejected')
            event = original_append(event_type, data, **options)
            if event_type == 'compaction/prune' and state['replacements'] == 0 and spec['recipe'] == 'snapshot':
                original_append('tool/result', dict(session.events[second]['data']), surface_op='append')
            return event
        session.append = intercept
        error, result = None, None
        try:
            result = pruner.prune_session(session)
        except Exception as caught:
            error = str(caught)
        session.append = original_append
        repeat = pruner.prune_session(session) if spec['recipe'] in ('preserve', 'multiple', 'invariants') else None
        replay = Session.create(session.id, list(session.events))
        events = [{key: value for key, value in event.items() if key != 'time'} for event in session.events]
        return wire(dict(mode=spec['mode'], result=result, error=error, repeat=repeat, rejection=rejection, events=events,
            nodes=list(session.surface.nodes), generation=session.surface.replace_generation,
            messages=session.derive_messages(), replayMessages=replay.derive_messages(),
            replayGeneration=replay.surface.replace_generation,
            originalPrice=meter.estimate_message(session.events[first]['data']['message'])))
    finally:
        await ctx.fiber.dispose()


async def main(output):
    specs = json.loads((ROOT / 'scripts/oracles/pruner-cases.json').read_text(encoding='utf-8'))
    results = [await observe(spec) for spec in specs]
    Path(output).write_text(json.dumps(results, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
