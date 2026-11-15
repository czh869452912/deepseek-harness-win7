"""Pair ordered PTC nested dispatch against the actual Source program bridge."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

ACTIONS = ('parallel', 'exclusive', 'reverse', 'pre-gate', 'post-gate', 'reclassify',
           'deny', 'pre-fails', 'body-fails', 'post-block', 'log-slow', 'log-fails', 'abandon', 'external-abort', 'limit')


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.tools import CurrentToolsPlugin, ToolExecutionInput, ToolRunContext, _json_snapshot
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tool_pipeline import ToolExecutionPipeline
    from dsh.core.ptc_dispatches import PtcDispatches
    from dsh.llm.message import create_user_message
    rows = []
    for action in ACTIONS:
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(CurrentToolsPlugin)
        controller = AbortController()
        events, starts, ends, pre, post, contexts = [], [], [], [], [], []
        gates = [asyncio.Event() for _ in range(4)]
        pre_gate, post_gate, log_gate = asyncio.Event(), asyncio.Event(), asyncio.Event()
        active = peak = 0
        reclassify = False
        row = dict(action=action)
        def append(kind, data):
            events.append(dict(type=kind, data=_json_snapshot(data)))
        agent = SimpleNamespace(ctx=ctx, session=SimpleNamespace(id='ptc', append=append))
        outer = ToolRunContext(ToolExecutionInput('outer', 'run_code', {}, agent=agent, signal=controller.signal))
        async def wait(predicate):
            async def loop():
                while not predicate():
                    await asyncio.sleep(.001)
            await asyncio.wait_for(loop(), 3)
        async def body(args, execution):
            nonlocal active, peak
            i = args['i']
            starts.append(i)
            active += 1
            peak = max(peak, active)
            try:
                if action in ('abandon', 'external-abort'):
                    await execution.signal.wait_aborted()
                    raise RuntimeError('canceled')
                await gates[i].wait()
                if action == 'body-fails' and i == 0:
                    raise RuntimeError('body refused')
                if i == 1:
                    execution.deferContext(create_user_message(dict(content=[dict(type='text', text='body-context')], source=dict(kind='test'))))
                    execution.concludeTurn()
                return dict(i=i)
            finally:
                active -= 1
                ends.append(i)
        def classify(args):
            return not ((action == 'exclusive' and args['i']==1)
                or action in ('abandon', 'external-abort') or (action == 'post-gate' and args['i']==0)
                or (action == 'reclassify' and args['i']==1 and reclassify))
        ctx.tools.register(dict(name='work', description='work', parameters=dict(type='object',
            properties=dict(i=dict(type='integer')), required=['i']), isConcurrencySafe=classify,
            execute=body, output=dict(schema=dict(type='object', properties=dict(i=dict(type='integer')), required=['i']),
                render=lambda args, value: [dict(type='text', text=str(value['i']))],
                presentationMeta=lambda args, value: dict(index=value['i']))))
        async def before(execution, next_fn):
            i = execution.arguments['i']
            pre.append(i)
            if action == 'pre-gate' and i == 0:
                await pre_gate.wait()
            if action == 'deny' and i == 0:
                return dict(kind='deny', reason='denied', info=dict(code='POLICY'))
            if action == 'pre-fails' and i == 0:
                raise RuntimeError('policy failed')
            return await next_fn()
        async def after(execution, result, next_fn):
            i = execution.arguments['i']
            post.append(i)
            if action == 'post-gate' and i == 0:
                await post_gate.wait()
            if action == 'post-block' and i == 0:
                return dict(kind='block', feedback=[dict(type='text', text='blocked')])
            return dict(kind='accept', additionalContexts=[create_user_message(dict(
                content=[dict(type='text', text='post-'+str(i))], source=dict(kind='test')))])
        async def shape(dispatch, next_fn):
            if action == 'log-slow':
                await log_gate.wait()
            if action == 'log-fails':
                raise RuntimeError('spill failed')
            return [dict(type='text', text='logged-'+dispatch['content'][0]['text'])]
        ctx.on('tools/pre-execute', before)
        ctx.on('tools/post-execute', after)
        ctx.on('tools/ptc-dispatch-log', shape)
        pipeline = ToolExecutionPipeline(ctx)
        queue = PtcDispatches(ctx, pipeline, outer, controller,
            1 if action == 'reclassify' else 3 if action == 'reverse' else 2,
            1 if action == 'limit' else 2048, 1 if action == 'limit' else 1024)
        binding = queue.binding(ctx.tools.schemas(agent)[0])
        async def result(future):
            try:
                return dict(value=_json_snapshot(await future))
            except Exception as error:
                return dict(error=getattr(error, 'message', str(error)))
        pending = []
        try:
            count = 2 if action in ('abandon', 'external-abort', 'limit') else 4 if action == 'log-slow' else 3
            pending = [asyncio.create_task(result(binding(dict(i=i)))) for i in range(count)]
            if action == 'pre-gate':
                await wait(lambda: pre == [0])
                row['serializedPrepare'] = starts == []
                pre_gate.set()
            if action in ('parallel', 'pre-gate'):
                await wait(lambda: len(starts) == 2)
            if action == 'reverse':
                await wait(lambda: len(starts)==3)
                gates[2].set()
                await wait(lambda: 2 in ends)
                gates[1].set()
                await wait(lambda: 1 in ends)
                row['orderedCommit'] = post == []
            if action in ('exclusive', 'reclassify', 'post-gate'):
                await wait(lambda: starts == [0])
                reclassify = True
                gates[0].set()
                if action == 'post-gate':
                    await wait(lambda: post == [0])
                    row['barrierThroughPost'] = starts == [0]
                    post_gate.set()
                await wait(lambda: 1 in starts)
                if action == 'post-gate':
                    await wait(lambda: len(starts) == 3)
                else:
                    row['exclusiveBarrier'] = 2 not in starts
            if action in ('abandon', 'external-abort'):
                await wait(lambda: starts == [0])
                if action == 'external-abort':
                    controller.abort(RuntimeError('external cancel'))
            for gate in gates:
                gate.set()
            if action == 'log-slow':
                await wait(lambda: all(future.done() for future in pending[:3]))
                row['logIndependent'] = not pending[3].done()
                log_gate.set()
            if action not in ('abandon', 'external-abort', 'limit'):
                row['bindings'] = await asyncio.gather(*pending)
            controller.abort('run_code settled')
            await queue.drain()
            if 'bindings' not in row:
                row['bindings'] = await asyncio.gather(*pending)
            row.update(pre=pre, starts=starts, ends=ends, post=post, peak=peak,
                contexts=[c['content'][0]['text'] for c in outer._additional_contexts],
                concluded=outer._concludes_turn, events=events, drained=not active)
            rows.append(row)
        finally:
            controller.abort('cleanup')
            for gate in gates + [pre_gate, post_gate, log_gate]:
                gate.set()
            await queue.drain()
            await asyncio.gather(*pending, return_exceptions=True)
            await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_dispatches.mts', 'Real Source run_code bridge and native nested pipeline: rolling bodies, ordered prepare/commit, exclusive barriers, late classification, policy/body failures, canonical results/contexts/metadata, durable logs/backpressure, abandonment and allowance cancellation.',
        [Path(__file__).resolve(), ROOT/'dsh/core/ptc_dispatches.py', ROOT/'dsh/core/tool_pipeline.py'])
