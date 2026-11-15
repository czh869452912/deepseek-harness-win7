"""One owned source subscription and bounded poll timer per output pump."""
import asyncio
import math
from types import SimpleNamespace

from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.core.cleanup import CleanupPromise


def field(value,key,default=None):
    return value.get(key,default) if isinstance(value,dict) else getattr(value,key,default)


def start_pump(sources,sink,poll_ms,until):
    if type(poll_ms) not in (int,float) or not math.isfinite(poll_ms) or poll_ms<=0:
        raise ValueError('invalid pump pollMs: expected a positive finite number of milliseconds, got '+stringify_json(poll_ms))
    states=[dict(source=source,cursor=0) for source in sources]
    async def run():
        settled=False;timer=None;wake=None
        def finish(_):
            nonlocal settled
            settled=True
            if timer is not None:timer.cancel()
            if wake is not None and not wake.done():wake.set_result(None)
            if not future.cancelled():future.exception()
        future=asyncio.ensure_future(until)
        future.add_done_callback(finish)
        def drain():
            for index,state in enumerate(states):
                source=state['source'];read=field(source,'read')(state['cursor']);state['cursor']=field(read,'nextOffset')
                field(sink,'spill')(index,field(read,'spillPath'))
                text=field(read,'text')
                if not text:continue
                channel=field(source,'channel');lossy=field(read,'lossy')
                if channel is None and not lossy:field(sink,'append')(text)
                else:
                    options={}
                    if channel is not None:options['channel']=channel
                    if lossy:options['gapBefore']=True
                    field(sink,'append')(text,options)
        try:
            while not settled:
                drain();wake=asyncio.get_running_loop().create_future()
                timer=asyncio.get_running_loop().call_later(poll_ms/1000,lambda:None if wake.done() else wake.set_result(None))
                await wake;wake=None;timer=None
            drain()
        finally:
            if timer is not None:timer.cancel()
            # Keep the sole settlement observer even when a source failed:
            # a later rejected producer still has an owned rejection handler.
    return SimpleNamespace(done=CleanupPromise(start_coroutine(run())))


startPump=start_pump
