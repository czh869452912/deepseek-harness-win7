"""Observe actual Python Agent maintenance and its real driver."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.llm.llm_service import LlmRuntime
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.core.session import SessionPlugin
from dsh.compaction.engine import CompactionEngine
from dsh.core.abort import AbortController
from dsh.llm.token_meter import TokenMeter
from dsh.llm.error import error_chain


async def compaction(spec):
    ctx = Context()
    release, reached = asyncio.Event(), asyncio.Event()
    pending = disposal = None
    try:
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(AgentPlugin)
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(LlmRuntime)
        await ctx.plugin(AgentLoopPlugin)
        TokenMeter(ctx)
        engine = CompactionEngine(ctx=ctx, config=dict(auto=False))
        handle = await ctx.get('agents').create(session_id=spec['mode'])
        agent = handle.agent
        markers, signals = [], []
        state = dict(flushes=0, retained=False)
        agent.ctx.disposable(lambda: markers.append('released'))
        agent.session.append_user_message('important facts ' * 300)
        agent.session.append_user_message('recent question')
        async def summarize(input, owner, signal):
            signals.append(signal)
            if spec['stage'] == 'summary':
                reached.set()
                await release.wait()
                state['retained'] = markers == []
            return dict(summary=[dict(type='text', text='checkpoint')], provider='probe', model='model')
        async def flush():
            state['flushes'] += 1
            if spec['stage'] == 'flush':
                reached.set()
                await release.wait()
            state['retained'] = markers == []
        engine.summarize, agent.session.flush = summarize, flush
        caller = AbortController()
        caller_cause, agent_cause = spec.get('reason', dict(kind='user')), dict(kind='parent')
        async def execute():
            try:
                await engine.compact_now(agent, caller.signal)
                return dict(code='unexpected-success', callerReason=False)
            except BaseException as error:
                return dict(code=getattr(error, 'code', None), callerReason=error is caller_cause or getattr(error, 'reason', None) is caller_cause,
                    rendered=error_chain(error))
        pending = asyncio.create_task(execute())
        await reached.wait()
        if spec['action'] == 'dispose':
            disposal = asyncio.create_task(handle.dispose())
        elif spec['action'] == 'agent-first':
            agent.cancel(agent_cause)
            caller.abort(caller_cause)
        else:
            caller.abort(caller_cause)
            agent.cancel(caller_cause if spec['action'] == 'shared-cause' else agent_cause)
        for _ in range(5):
            await asyncio.sleep(0)
        before = dict(pending=disposal is None or not disposal.done(), retained=markers == [],
            registered=ctx.get('agents').get(agent.id) is agent and ctx.get('sessions').get(agent.id) is agent.session,
            aborted=signals[0].aborted)
        release.set()
        outcome = await pending
        if disposal is not None:
            await disposal
        else:
            await handle.dispose()
        return dict(mode=spec['mode'], before=before, outcome=outcome, retainedInJob=state['retained'],
            flushes=state['flushes'], released=markers,
            clean=ctx.get('agents').get(agent.id) is None and ctx.get('sessions').get(agent.id) is None,
            generation=agent.session.surface.replace_generation,
            failedEnds=[e['data']['error'] for e in agent.session.events if e['type'] == 'compaction/end' and 'error' in e['data']],
            events=[dict(type=e['type'], failed='error' in e['data']) for e in agent.session.events if e['type'].startswith('compaction/')])
    finally:
        release.set()
        await asyncio.gather(*(task for task in (pending, disposal) if task is not None), return_exceptions=True)
        await ctx.fiber.dispose()


async def observe(spec):
    ctx = Context()
    release, reached = asyncio.Event(), asyncio.Event()
    turn_release, turn_reached = asyncio.Event(), asyncio.Event()
    try:
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(AgentPlugin)
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(LlmRuntime)
        await ctx.plugin(AgentLoopPlugin)
        handle = await ctx.get('agents').create(session_id=spec['mode'])
        agent = handle.agent
        claims = []
        async def pre_step(payload, next_fn):
            claims.extend(block['text'] for message in payload['messages'] for block in message['content'] if block['type'] == 'text')
            turn_reached.set()
            await turn_release.wait()
            return dict(kind='reject')
        ctx.on('agent/pre-step', pre_step)
        def send(text, wake=True):
            return agent.followup(text) if wake else agent.inject(text)
        if spec.get('idleCancel'):
            send('parked', False)
            agent.cancel(dict(kind='user'), keep_inbox=True)
        failure = RuntimeError('job failed')
        signals = []
        async def job(signal):
            signals.append(signal)
            reached.set()
            await release.wait()
            if spec.get('error'):
                raise failure
            return 42
        operation = agent.run_maintenance(job)
        reserved = agent.status == 'idle'
        busy = False
        try:
            agent.run_maintenance(lambda signal: None)
        except RuntimeError:
            busy = True
        async def result():
            try:
                return dict(value=await operation)
            except Exception as error:
                return dict(sameFailure=error is failure)
        pending = asyncio.create_task(result())
        await reached.wait()
        idle = asyncio.create_task(agent.when_idle())
        for _ in range(3):
            await asyncio.sleep(0)
        waits_maintenance = not idle.done()
        first = dict(kind=spec.get('cancel', 'user'))
        if spec.get('wake'):
            wake_id = send('queued')
        if spec.get('inject'):
            send('injected', False)
        if spec.get('remove'):
            agent.inbox.remove(wake_id)
        if spec.get('cancel'):
            agent.cancel(first, keep_inbox=spec.get('keep', False))
        if spec.get('secondCancel'):
            agent.cancel(dict(kind='disposed'), keep_inbox=True)
        if spec.get('afterWake'):
            send('after cancel')
        signal = signals[0]
        cancellation = dict(aborted=signal.aborted, firstReason=signal.aborted and signal.reason is first)
        release.set()
        outcome = await pending
        expect_turn = ((spec.get('wake') and not spec.get('remove') and (not spec.get('cancel') or spec.get('keep')))
                       or (spec.get('afterWake') and spec.get('cancel') != 'disposed'))
        waits_driver = False
        if expect_turn:
            await asyncio.wait_for(turn_reached.wait(), 2)
            for _ in range(3):
                await asyncio.sleep(0)
            waits_driver = not idle.done()
        turn_release.set()
        await asyncio.wait_for(idle, 2)
        row = dict(mode=spec['mode'], reserved=reserved, busy=busy, waitsMaintenance=waits_maintenance,
            waitsDriver=waits_driver, cancellation=cancellation, outcome=outcome, claims=claims,
            status=agent.status, queued=len(agent.inbox.next_turn) + len(agent.inbox.next_step),
            turns=[event['type'] for event in agent.session.events if event['type'] in ('turn/start', 'turn/end')])
        await handle.dispose()
        return row
    finally:
        release.set()
        turn_release.set()
        await ctx.fiber.dispose()


async def main():
    cases = json.loads((Path(__file__).parent / 'maintenance-cases.json').read_text(encoding='utf-8'))
    rows = [await compaction(spec) if spec.get('kind') == 'compaction' else await observe(spec) for spec in cases]
    Path(sys.argv[1]).write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
