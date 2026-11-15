"""Pair complete program call/reset ownership with fixed upstream PTC calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.ptc_calls import PtcCalls
    rows=[]
    for action in ('policy','external-abort','waiting-abort','no-policy','failed-call',
                   'reset','release-fails','notify-fails','dispose','dispose-reset'):
        ctx=Context();calls=PtcCalls(ctx);controller=AbortController();current_mode='workspace-write'
        trace=[];signals=[];loop=asyncio.get_running_loop();cleanup=loop.create_future();started=loop.create_future();released=loop.create_future();aborted=loop.create_future();tasks=[]
        row=dict(action=action)
        def mode():
            trace.append('mode:'+str(current_mode));return None if action=='no-policy' else current_mode
        async def body(signal):
            signals.append(signal)
            signal.add_listener('abort',lambda reason:None if aborted.done() else aborted.set_result(None))
            trace.append('first');await asyncio.shield(cleanup);trace.append('cleanup');return 'first'
        async def next_body(signal):
            trace.append('next');return 'next'
        async def independent(signal):
            return 'independent'
        async def result(future):
            try:return await future
            except Exception as error:return dict(message=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        async def release():
            trace.append('release');started.set_result(None);await asyncio.shield(released)
            if action=='release-fails':raise RuntimeError('release failed')
        def notify():
            trace.append('notice')
            if action=='notify-fails':raise RuntimeError('notice failed')
        first=calls.run('session',controller.signal,mode,body);tasks.append(first)
        try:
            ctx.emit('session/event',SimpleNamespace(id='other'),dict(type='sandbox/mode',data=dict(mode='read-only')))
            ctx.emit('session/event',SimpleNamespace(id='session'),dict(type='turn/start',data=dict(turn=1)))
            ctx.emit('session/event',SimpleNamespace(id='session'),dict(type='sandbox/mode',data=dict(mode='workspace-write')))
            row['unrelatedIgnored']=not signals[0].aborted
            if action in ('policy','external-abort','waiting-abort','no-policy'):
                current_mode='read-only'
                if action=='external-abort':controller.abort(RuntimeError('caller canceled'))
                else:ctx.emit('session/event',SimpleNamespace(id='session'),dict(type='sandbox/mode',data=dict(mode=current_mode)))
                row['aborted']=signals[0].aborted
                successor=AbortController();second=calls.run('session',successor.signal,mode,next_body);tasks.append(second)
                row['blocked']='next' not in trace
                if action=='waiting-abort':successor.abort(RuntimeError('waiting canceled'))
                current_mode='danger-full-access'
                cleanup.set_result(None);row['first']=await result(first);row['next']=await result(second)
            elif action=='failed-call':
                async def fail(signal):raise RuntimeError('call failed')
                row['failed']=await result(calls.run('session',AbortController().signal,mode,fail))
                row['next']=await result(calls.run('session',AbortController().signal,mode,next_body))
                row['overlap']=not cleanup.done();cleanup.set_result(None);await first
            elif action in ('reset','release-fails','notify-fails','dispose-reset'):
                reset=calls.reset('session',release,notify);tasks.append(reset)
                row['aborted']=signals[0].aborted;row['sharedReset']=calls.reset('session',release) is reset
                second=calls.run('session',AbortController().signal,mode,next_body);tasks.append(second)
                await started
                row['blocked']='next' not in trace
                row['independent']=await calls.run('other',AbortController().signal,lambda:None,independent)
                released.set_result(None)
                row['releaseInsufficient']='next' not in trace and 'notice' not in trace
                if action=='dispose-reset':
                    disposed=ctx.fiber.dispose();tasks.append(disposed)
                    # The root's async effect enters before it awaits active calls.
                    await aborted
                cleanup.set_result(None);await first
                row['reset']=await result(reset);row['next']=await result(second)
                if action in ('release-fails','notify-fails'):
                    row['blockedAfterFailure']=await result(calls.run('session',AbortController().signal,mode,next_body))
                    await calls.reset('session',lambda:None)
                    row['retry']=await result(calls.run('session',AbortController().signal,mode,next_body))
                if action=='dispose-reset':await disposed
            else:
                disposed=ctx.fiber.dispose();tasks.append(disposed);await aborted
                row['aborted']=signals[0].aborted
                second=calls.run('session',AbortController().signal,mode,next_body);tasks.append(second)
                row['blocked']='next' not in trace;cleanup.set_result(None);await first
                row['next']=await result(second);await disposed
            if action in ('dispose','dispose-reset'):
                row['late']=await result(calls.run('session',AbortController().signal,mode,next_body))
                row['lateReset']=await result(calls.reset('session',lambda:None))
            row['trace']=trace
            rows.append(row)
        finally:
            if not cleanup.done():cleanup.set_result(None)
            if not released.done():released.set_result(None)
            await asyncio.gather(*tasks,return_exceptions=True)
            await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_ptc_calls.mts','PTC complete-call cancellation, policy freshness, host reset barriers, failed release/notice retry, unrelated sessions and executor disposal.',
        [Path(__file__).resolve(),ROOT/'dsh/core/ptc_calls.py'])
