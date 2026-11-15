"""Pair the Agent registry's archive admission and resource declarations."""
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
    from dsh.typert.current import CurrentTypertRegistry
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    class Types(Plugin):
        def apply(self,ctx):CurrentTypertRegistry(ctx)
    rows=[]
    for action in ('states','running-to-idle','idle-to-running','stop','stop-throws','dispose','types-before','types-after'):
        ctx=Context();row=dict(action=action);jobs=[];releases=[]
        try:
            await ctx.plugin(Registry)
            if action=='types-before':await ctx.plugin(Types)
            fiber=await ctx.plugin(CurrentAgentPlugin);agents=ctx.get('agents');calls=[]
            def cancel(*args):calls.append([args[0],args[1] if len(args)>1 else None])
            agent=SimpleNamespace(id='busy',session=SimpleNamespace(id='busy'),ctx=ctx,status='running',cancel=cancel)
            detach=agents.enter(agent)
            async def end():return []
            async def ask(sid='busy'):return await ctx.waterfall('workspace/session-activity',dict(sessionId=sid),end)
            async def stop(sid='busy'):await ctx.parallel('workspace/session-stop',dict(sessionId=sid))
            if action=='states':
                async def later(request,next_fn):return (await next_fn())+[dict(kind='probe')]
                ctx.on('workspace/session-activity',later)
                row['running']=await ask();agent.status='idle';row['idle']=await ask();row['unknown']=await ask('unknown');detach();row['detached']=await ask()
            elif action in ('running-to-idle','idle-to-running'):
                started=asyncio.Event();release=asyncio.Event();releases.append(release);rest=[dict(kind='probe')]
                async def later(request,next_fn):started.set();await release.wait();return rest
                ctx.on('workspace/session-activity',later)
                agent.status='running' if action=='running-to-idle' else 'idle'
                task=asyncio.ensure_future(ask());jobs.append(task);await started.wait();agent.status='idle' if agent.status=='running' else 'running';release.set();result=await task
                row.update(result=result,same=result is rest)
            elif action=='stop':
                pending=asyncio.get_running_loop().create_future()
                def no_wait(*args):cancel(*args);return pending
                agent.cancel=no_wait;await stop();row['calls']=list(calls);row['notAwaited']=not pending.done();pending.cancel();agent.status='idle';await stop();await stop('unknown');row['afterIdle']=len(calls)
            elif action=='stop-throws':
                primary=RuntimeError('cancel failed')
                def fail(*args):raise primary
                agent.cancel=fail
                try:await stop()
                except Exception as error:row.update(same=error is primary,contained=error.errors[0] is primary,count=len(error.errors))
            elif action=='dispose':
                row['before']=await ask();await fiber.dispose();row['after']=await ask();await stop();row['calls']=calls
            else:
                if action=='types-after':await ctx.plugin(Types)
                types=ctx.get('typert');lookup=types.lookups.get('agent');adapter=types.contexts.getHost('agent')
                row.update(lookup={key:lookup[key] for key in ('parameter','wire','resource','hostTypeSymbol','wireTypeSymbol')},context={key:adapter[key] for key in ('wire','resource','wireTypeSymbol')},resolved=lookup['resolve']('busy') is agent,scoped=adapter['resolve']('busy') is ctx,unknown=lookup['resolve']('unknown') is None)
                await fiber.dispose();row['withdrawn']=types.lookups.get('agent') is None and types.contexts.getHost('agent') is None
            rows.append(row)
        finally:
            for release in releases:release.set()
            if jobs:await asyncio.gather(*jobs,return_exceptions=True)
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_archive.mts','Live turn archive activity captured before downstream waits, user stop without keepInbox or settlement, listener teardown, Agent lookup/Context session resource declarations before and after Typert mount.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_current.py',ROOT/'dsh/core/agent.py'])
