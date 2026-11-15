"""Observe serial Agent creation, paired rollback and exact effect ownership."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.abort import AbortController
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('serial','sync-reject','async-reject','detach-await','split-stale','payload','owner-order','reentrant-announce','effect-repeat','effect-awaited','effect-owner-join'):
        ctx=Context();trace=[];row=dict(action=action);release=asyncio.Event();entered=asyncio.Event();jobs=[]
        try:
            await ctx.plugin(Registry);await ctx.plugin(CurrentAgentPlugin);agents=ctx.get('agents')
            agent=SimpleNamespace(id='agent',session=SimpleNamespace(id='agent'),ctx=ctx)
            ctx.on('agent/disposed',lambda payload:trace.append('disposed'))
            if action.startswith('effect-'):
                owners=[]
                class Owner(Plugin):
                    def apply(self,scope):owners.append(scope)
                owner_fiber=await ctx.plugin(Owner);owner=owners[0]
                async def cleanup():trace.append('cleanup:start');entered.set();await release.wait();trace.append('cleanup:end')
                disposer=owner.effect(lambda:cleanup,'test pending effect')
                selected=await disposer if action=='effect-awaited' else disposer
                row['different']=selected is not disposer
                first=selected();jobs.append(first);await entered.wait();row['repeat']=selected() is None;row['wrapperRepeat']=disposer() is None
                if action=='effect-owner-join':
                    closing=asyncio.ensure_future(owner_fiber.dispose());jobs.append(closing);await asyncio.sleep(0);row['waiting']=not closing.done()
                release.set();await asyncio.gather(*jobs);row['trace']=list(trace);row['after']=selected() is None
            elif action in ('serial','detach-await'):
                async def first(payload):
                    trace.append('first:start')
                    if action=='detach-await':detach();trace.append('live' if agents.get('agent') is agent else 'missing')
                    entered.set();await release.wait();trace.append('first:end')
                ctx.on('agent/created',first);ctx.on('agent/created',lambda payload:trace.append('second'))
                if action=='detach-await':detach=agents.enter(agent);registration=agents.announce(agent,'resume')
                else:registration=agents.register(agent)
                async def ready():await registration;trace.append('ready')
                job=asyncio.ensure_future(ready());jobs.append(job);await entered.wait();row['waiting']=list(trace)
                try:await agents.announce(agent,'startup')
                except Exception as error:row['reentrant']=str(error)
                release.set();await job;row['settled']=list(trace);row['live']=agents.get('agent') is agent
                if action=='serial':await registration();row['disposed']=list(trace);row['repeat']=registration() is None
            elif action in ('sync-reject','async-reject'):
                primary=RuntimeError('creation rejected')
                def fail(payload):trace.append('rejected');raise primary
                async def fail_later(payload):trace.append('first:start');await asyncio.sleep(0);fail(payload)
                ctx.on('agent/created',fail if action=='sync-reject' else fail_later)
                ctx.on('agent/created',lambda payload:trace.append('unreachable'))
                try:await agents.register(agent)
                except Exception as error:row['same']=error is primary
                row['trace']=list(trace);row['removed']=agents.get('agent') is None
            elif action=='split-stale':
                detach=agents.enter(agent);row['unannounced']=list(trace);await agents.announce(agent,'startup');detach();detach()
                replacement=SimpleNamespace(id='agent',session=SimpleNamespace(id='agent'),ctx=ctx);remove=agents.enter(replacement);detach();row['replacement']=agents.get('agent') is replacement
                try:await agents.announce(agent,'startup')
                except Exception as error:row['stale']=str(error)
                remove();row['trace']=list(trace)
            elif action=='payload':
                signal=AbortController().signal
                def listener(payload):row.update(subject=payload['agent'] is agent,source=payload['source'],signal=payload.get('signal') is signal,keys=sorted(payload))
                ctx.on('agent/created',listener);detach=agents.enter(agent);await agents.announce(agent,'compaction',signal);detach()
            elif action=='owner-order':
                owners=[]
                class Owner(Plugin):
                    inject=['agents']
                    def apply(self,scope):owners.append(scope)
                owner_fiber=await ctx.plugin(Owner);owner=owners[0];registration=owner.get('agents').register(agent);await registration
                async def drain():trace.append('drain:start');entered.set();await release.wait();trace.append('drain:end')
                def lifecycle():yield registration;yield drain
                owner.effect(lifecycle,'ordered agent lifetime');job=asyncio.ensure_future(owner_fiber.dispose());jobs.append(job);await entered.wait();row['waiting']=list(trace);row['liveBefore']=agents.get('agent') is agent;release.set();await job;row['trace']=list(trace);row['removed']=agents.get('agent') is None
            else:
                async def listener(payload):
                    try:await agents.announce(agent,'startup')
                    except Exception as error:row['reentrant']=str(error)
                ctx.on('agent/created',listener);registration=agents.register(agent);await registration;row['live']=agents.get('agent') is agent;await registration()
            rows.append(row)
        finally:
            release.set()
            if jobs:await asyncio.gather(*jobs,return_exceptions=True)
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_agent_registration.mts','Awaited serial creation, direct rejection identity and rollback, deferred detach through async listeners, announcement payload, stale entry identity and exact disposer nesting.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_current.py',ROOT/'dsh/core/agent_loop_current.py',ROOT/'dsh/cordis/fiber.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/fiber.ts'])
