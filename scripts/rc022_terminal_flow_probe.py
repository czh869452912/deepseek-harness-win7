"""Terminal follower frames and retention decisions under a controlled monotonic clock."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


class Clock:
    def __init__(self):self.time=0;self.timers=[];self.order=0
    def now(self):return self.time
    def later(self,delay,callback):
        from types import SimpleNamespace as NS
        self.order+=1;timer=NS(due=self.time+delay,callback=callback,cancelled=False,order=self.order)
        timer.cancel=lambda:setattr(timer,'cancelled',True);self.timers.append(timer);return timer
    async def pump(self):
        for _ in range(20):await asyncio.sleep(0)
    async def advance(self,amount):
        end=self.time+amount
        while True:
            ready=sorted([timer for timer in self.timers if not timer.cancelled and timer.due<=end],key=lambda timer:(timer.due,timer.order))
            if not ready:break
            timer=ready[0];timer.cancelled=True;self.time=timer.due;timer.callback();await self.pump()
        self.time=end;await self.pump()
    def count(self):return sum(not timer.cancelled for timer in self.timers)


async def observe():
    from dsh.api.terminal_stream_authorized import TerminalFollower
    from dsh.api.terminal_retention_authorized import TerminalRetention
    from dsh.core.abort import AbortController
    from dsh.cordis.json_text import stringify_json
    rows=[];frame=dict(type='output',sequence=1,data='终端😀\ufeff')
    maximum=len(stringify_json(frame).encode('utf-8'))
    follower=TerminalFollower(maximum);controller=AbortController();stream=follower.read(controller.signal)
    follower.push(frame);one=await stream.__anext__();follower.push(frame);follower.finish();follower.fail(RuntimeError('ignored after finish'))
    rows.append(dict(name='exact-follower-bound',maximum=maximum,frames=[one]+[item async for item in stream],active=follower.active))
    follower=TerminalFollower(maximum);follower.push(frame);follower.push(frame)
    try:await follower.read(AbortController().signal).__anext__()
    except RuntimeError as error:rows.append(dict(name='follower-overflow',error=str(error),active=follower.active))
    follower=TerminalFollower(1000);follower.push(frame);controller=AbortController();controller.abort()
    rows.append(dict(name='preaborted-follower',frames=[item async for item in follower.read(controller.signal)]))
    follower=TerminalFollower(1000);controller=AbortController();stream=follower.read(controller.signal);reading=asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0);follower.push(frame);first=await reading;ending=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0);controller.abort()
    try:await ending
    except StopAsyncIteration:pass
    rows.append(dict(name='waiting-follower',first=first,active=follower.active));await stream.aclose()
    for scenario in ('idle','holds','busy','unknown','revision','retry','huge-retry'):
        clock=Clock();calls=[];errors=[];observations=[];activity=dict(state='idle',revision=1);failed_once=[scenario in ('retry','huge-retry')]
        async def inspect():observations.append(clock.now());return dict(activity)
        async def terminate():
            calls.append(clock.now())
            if failed_once[0]:failed_once[0]=False;raise RuntimeError('still alive')
        policy=dict(unattendedTimeoutMs=100,activityPollIntervalMs=10,cleanupRetryMs=20)
        if scenario=='huge-retry':policy.update(unattendedTimeoutMs=0,cleanupRetryMs=3000000000)
        owner=TerminalRetention(policy,inspect,terminate,lambda error:errors.append(str(error)),clock);streams=[]
        try:
            if scenario=='holds':
                first,second=AbortController(),AbortController();a=owner.retain(first.signal);b=owner.retain(second.signal);streams=[a,b]
                await a.__anext__();await b.__anext__();first.abort();await clock.advance(500);second.abort();await clock.advance(99)
            elif scenario in ('busy','unknown'):
                activity['state']=scenario;await clock.advance(1000);activity.update(state='idle',revision=2);await clock.advance(109)
            elif scenario=='revision':
                await clock.advance(90);owner.invalidate();activity['revision']=2;await clock.advance(109)
            elif scenario=='huge-retry':
                try:await owner.close()
                except RuntimeError as error:errors.append(str(error))
                await clock.advance(2999999999)
            else:await clock.advance(99)
            rows.append(dict(name=scenario+'-before',calls=list(calls),errors=list(errors)))
            await clock.advance(1)
            if scenario=='retry':
                try:await owner.retain(AbortController().signal).__anext__()
                except Exception as error:rows.append(dict(name='closed-on-failure',code=error.code))
                await clock.advance(20)
            rows.append(dict(name=scenario+'-after',calls=list(calls),errors=list(errors)))
        finally:
            await owner.dispose()
            for stream in streams:await stream.aclose()
        rows.append(dict(name=scenario+'-disposed',timers=clock.count()))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_flow.mts','Actual TerminalFollower and TerminalRetention classes with deterministic monotonic timers: exact encoded frame bytes, overflow/detach/cancellation/drain; idle grace, independent window holds, busy/unknown protection, revision reset, failed cleanup closed identity/retry, bounded native timer preserving huge retry and timer-free disposal. No PTY or screen emulator acceptance.',
        [Path(__file__).resolve(),ROOT/'dsh/api/terminal_stream_authorized.py',ROOT/'dsh/api/terminal_retention_authorized.py'])
