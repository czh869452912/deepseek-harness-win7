"""Workflow result ownership when one observer stops awaiting."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def scenario(kind):
    from dsh.workflow.ptc_run import PtcWorkflowRun
    from dsh.core.abort import AbortController
    entered, release, closing, closed = (asyncio.Event() for _ in range(4))
    external = AbortController()
    callbacks, disposed = [], []
    async def ensure(*args): return 'C:/fixed'
    async def dispose():
        closing.set()
        await closed.wait()
        disposed.append('child')
    async def start(_spec):
        future = asyncio.get_running_loop().create_future()
        future.set_result(dict(output=[], stopReason='completed'))
        return SimpleNamespace(childId='child', result=future, dispose=dispose)
    async def execute(spec):
        if kind == 'teardown':
            await spec['bindings'][0]['functions']['startChild'](dict(prompt='child'))
        entered.set()
        await release.wait()
        if kind == 'runtime-error': raise ValueError('runtime rejected')
        return dict(value=dict(value=7, stopReason='completed', agentsStarted=1 if kind == 'teardown' else 0))
    ctx = SimpleNamespace(get=lambda _: SimpleNamespace(ensure=ensure), logger=SimpleNamespace(warn=lambda _: None))
    runtime = SimpleNamespace(sandboxMode='read-only', programFormat='function-body', resolve=lambda x: x, run=execute)
    run = PtcWorkflowRun(ctx, SimpleNamespace(startActivation=start), runtime, 'run', dict(name='held'),
        None, {}, 'stub', dict(mode='read-only'), None, external.signal)
    result = run.result
    result.add_done_callback(lambda value: callbacks.append(value is result))
    if kind != 'early-observer': await entered.wait()
    if kind == 'teardown':
        release.set()
        await closing.wait()
    async def wait(): return await result
    first = asyncio.create_task(wait())
    second = asyncio.create_task(wait())
    await asyncio.sleep(0)
    if kind == 'timeout':
        try: await asyncio.wait_for(first, 0.01)
        except asyncio.TimeoutError: pass
    else:
        first.cancel()
        try: await first
        except asyncio.CancelledError: pass
    pending = not result.done() and not second.done()
    still_active = not run.controller.signal.aborted
    held_children = len(run.children)
    if kind == 'owner-cancel': run.cancel('holder stopped')
    release.set(); closed.set()
    answer = await second
    await run.dispose()
    await asyncio.sleep(0)
    if 'error' in answer: answer['error'] = answer['error'].splitlines()[0]
    return dict(kind=kind, pending=pending, stillActive=still_active, heldChildren=held_children,
        sameHandle=run.result is result, sameValue=await result is answer, result=answer,
        callbacks=callbacks, disposed=disposed, pendingJobs=len(run.pending), children=len(run.children),
        detached=not external.signal._listeners)


async def observe():
    return [await scenario(kind) for kind in ('abandoned-observer', 'timeout', 'early-observer', 'teardown', 'runtime-error', 'owner-cancel')]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_workflow_result.mts', scope='Original holder-owned Workflow result compared with independent Python observer cancellation/timeout. JS observer abandonment uses Promise.race; only run.cancel aborts the owner. Held runtime, pre-drive observer, child disposal, runtime rejection and explicit owner cancellation.',
        extra_inputs=[Path(__file__).resolve(), ROOT/'dsh/workflow/ptc_run.py', ROOT/'dsh/core/cleanup.py'])
