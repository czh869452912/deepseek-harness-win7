"""Strict zero-argument inner and eager continuation dispatch observations."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import EventBus
    result={}
    bus=EventBus();seen=[]
    def listener(*args):
        seen.append(list(args[:-1]));return args[-1]('ignored',42)
    bus.on('chain',listener);bus.on('chain',listener)
    result['inner']=bus.waterfall_sync('chain','a',1,lambda *args:list(args))
    result['listener_args']=seen
    for mode,values in (('no-inner',[]),('seed-only',['seed']),('non-callable',[1,False])):
        try:EventBus().waterfall_sync('chain',*values)
        except Exception as error:result[mode]=type(error).__name__
    bus=EventBus();bus.on('chain',lambda:'veto')
    result['veto']=bus.waterfall_sync('chain')
    bus=EventBus();bus.on('chain',lambda next_fn:next_fn)
    result['named_next']=bus.waterfall_sync('chain','original',lambda:'end')
    trace=[];release=asyncio.Event();bus=EventBus()
    async def inner():trace.append('inner-before');await release.wait();trace.append('inner-after');return 'end'
    async def outer(value,next_fn):
        trace.append('outer-before');pending=next_fn();trace.append('outer-next-returned')
        value=await pending;trace.append('outer-after');return value+'!'
    bus.on('chain',outer)
    pending=bus.waterfall_sync('chain','input',inner)
    result['prefix']=list(trace);release.set();result['async_result']=await pending;result['trace']=trace
    bus=EventBus();trace=[]
    async def await_sync(value,next_fn):
        trace.append('before');pending=next_fn();trace.append('next-returned');answer=await pending
        trace.append('after');return answer
    bus.on('chain',await_sync)
    result['await_sync']=await bus.waterfall('chain','input',lambda:trace.append('inner') or 42)
    result['await_sync_trace']=trace
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_waterfall.mts',scope=__doc__,extra_inputs=[ROOT/'dsh/cordis/awaiting.py',Path(__file__).resolve()])
