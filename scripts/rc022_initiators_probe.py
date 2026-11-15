"""Observe registry-local initiator boundaries and reentrant unload drains."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.fiber import FiberState
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    async def mount():
        ctx=Context();await ctx.plugin(Registry);fiber=await ctx.plugin(CurrentAgentPlugin)
        return ctx,fiber,ctx.get('agents')
    def read(service):
        try:
            value=service.currentInitiator();return dict(value=None if value is None else value.id)
        except Exception as error:return dict(error=str(error))
    rows=[]
    for action in ('sync','nested','overlap','drain','self-dispose','ancestor-dispose','async-unrelated','cross-registry','promise-identity','plain-awaitable','throws'):
        ctx,fiber,service=await mount();releases=[];jobs=[];other_ctx=None;row=dict(action=action);a=SimpleNamespace(id='a');b=SimpleNamespace(id='b')
        try:
            if action=='sync':
                value={};row['same']=service.withInitiator(a,lambda:(row.update(inside=read(service)),value)[1]) is value;row['outside']=read(service)
            elif action=='nested':
                trace=[]
                def outer():
                    trace.append(read(service));service.withInitiator(b,lambda:trace.append(read(service)));trace.append(read(service));service.withoutInitiator(lambda:trace.append(read(service)));trace.append(read(service))
                service.withInitiator(a,outer);row['trace']=trace;row['outside']=read(service)
            elif action in ('overlap','drain','async-unrelated'):
                release=asyncio.Event();releases.append(release);trace=[]
                async def run(agent):
                    trace.append(read(service));await release.wait();trace.append(read(service))
                if action=='overlap':
                    jobs=[service.withInitiator(a,lambda:run(a)),service.withInitiator(b,lambda:run(b))];row['outside']=read(service);release.set();await asyncio.gather(*jobs);row['trace']=trace
                elif action=='drain':
                    job=service.withInitiator(a,lambda:run(a));jobs.append(job);closing=asyncio.ensure_future(fiber.dispose());row['state']=service.initiatorState;row['hidden']=ctx.get('agents') is None;row['waiting']=not closing.done()
                    for key,operation in (('with',lambda:service.withInitiator(b,lambda:1)),('without',lambda:service.withoutInitiator(lambda:1))):
                        try:operation()
                        except Exception as error:row[key]=str(error)
                    release.set();await job;await closing;row['trace']=trace;row['after']=read(service)
                else:
                    sibling=service.withInitiator(b,lambda:run(b));jobs.append(sibling);closed=asyncio.Event()
                    ctx.on('internal/status',lambda owner,*_args:closed.set() if getattr(owner,'state',None)==FiberState.UNLOADING else None)
                    async def shutdown():
                        await asyncio.sleep(0);await ctx.fiber.dispose()
                    own=service.withInitiator(a,shutdown);jobs.append(own);await asyncio.wait_for(closed.wait(),2);row['waiting']=not own.done();row['state']=service.initiatorState;release.set();await asyncio.wait_for(asyncio.gather(*jobs),2);row['trace']=trace;row['after']=read(service)
            elif action in ('self-dispose','ancestor-dispose'):
                returned=[]
                def shutdown():
                    result=asyncio.ensure_future((fiber if action=='self-dispose' else ctx.fiber).dispose());returned.append(result);return result
                result=service.withInitiator(a,shutdown) if action=='self-dispose' else service.withInitiator(a,lambda:service.withInitiator(b,shutdown))
                jobs.append(result);row['same']=result is returned[0];await asyncio.wait_for(result,2);row['after']=read(service)
            elif action=='cross-registry':
                other_ctx,other_fiber,other=await mount();row['other']=service.withInitiator(a,lambda:read(other));row['own']=service.withInitiator(a,lambda:read(service));await other_fiber.dispose()
            elif action=='promise-identity':
                value=asyncio.get_running_loop().create_future();jobs.append(value);row['same']=service.withInitiator(a,lambda:value) is value;closing=asyncio.ensure_future(fiber.dispose());row['waiting']=not closing.done();value.set_result('done');await value;await closing;row['after']=read(service)
            elif action=='plain-awaitable':
                class Plain:
                    def __await__(self):raise AssertionError('custom awaitable must not be assimilated')
                value=Plain();row['same']=service.withInitiator(a,lambda:value) is value;await fiber.dispose();row['after']=read(service)
            else:
                primary=RuntimeError('sync failure')
                def fail():raise primary
                try:service.withInitiator(a,fail)
                except Exception as error:row['syncSame']=error is primary
                async def reject():await asyncio.sleep(0);raise primary
                job=service.withInitiator(b,reject);jobs.append(job)
                try:await job
                except Exception as error:row['asyncSame']=error is primary
                row['outside']=read(service)
            rows.append(row)
        finally:
            for release in releases:release.set()
            if jobs:await asyncio.gather(*jobs,return_exceptions=True)
            if other_ctx is not None:await other_ctx.fiber.dispose()
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_initiators.mts','Registry-local initiator storage, exact returned Future identity, async prefix/tail isolation, closing admission and own-lineage exclusion while unrelated work drains.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_current.py',ROOT/'dsh/core/agent.py'])
