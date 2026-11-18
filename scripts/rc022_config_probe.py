"""Compare raw/effective config and lifecycle journeys with fixed Source."""
import asyncio
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context
    result={}
    ctx=Context();applied=[];raw={'value':0}
    def plugin(owner,config):applied.append(config)
    fiber=ctx.plugin(plugin,raw);await fiber
    ctx.on('internal/config',lambda target,next_fn:dict(next_fn(),resolved=True))
    candidate={'value':1};evaluated=fiber.resolveConfig(candidate)
    result['candidate']=[evaluated,fiber.rawConfig is raw,fiber.config is raw,fiber.effectiveConfig is applied[0],len(applied)]
    await fiber.update(candidate)
    result['applied']=[fiber.rawConfig is candidate,fiber.effectiveConfig is applied[-1],fiber.effectiveConfig is not evaluated,applied]
    await ctx.fiber.dispose()

    ctx=Context();old=asyncio.Future();failed=asyncio.Future();commits=[];applied=[]
    ctx.on('internal/commit',lambda fiber,raw:commits.append(raw))
    def plugin(owner,config):
        applied.append(config)
        owner.on('internal/update',lambda candidate:old if candidate==1 else failed if candidate==3 else None)
    fiber=ctx.plugin(plugin,0);await fiber
    first=fiber.update(1);initial=fiber.effectiveConfig;sync=fiber.update(2) is None
    old.set_result(None);await first;after=fiber.effectiveConfig;third=fiber.update(3)
    failed.set_exception(ValueError('update rejected'));error=''
    try:await third
    except ValueError as reason:error=str(reason)
    result['retained']=[initial,sync,after,error,fiber.rawConfig,fiber.effectiveConfig,commits,applied]
    await ctx.fiber.dispose()

    for action in ('raw retention','restart','dispose'):
        ctx=Context();gate=asyncio.Future();applied=[]
        def plugin(owner,config):
            applied.append(config);owner.on('internal/update',lambda:gate)
        fiber=ctx.plugin(plugin,{'value':0});await fiber;old=fiber.update({'value':1})
        if action=='raw retention':fiber.rawConfig={'value':2}
        elif action=='restart':await fiber.restart()
        else:await fiber.dispose()
        gate.set_result(None);await old
        result[action]=[fiber.effectiveConfig is applied[-1],fiber.effectiveConfig,applied]
        await ctx.fiber.dispose()

    for injected in (False,True):
        ctx=Context();started=asyncio.Event();release=asyncio.Event();applied=[];disposed=[]
        ctx.provide('dependency',1)
        async def plugin(owner,config):
            applied.append(config)
            if config==1:started.set();await release.wait()
            owner.effect(lambda:lambda:disposed.append(config))
        plugin.inject=['dependency'] if injected else []
        fiber=ctx.plugin(plugin,0);await fiber;first=fiber.update(1);await started.wait()
        second=fiber.update(2);third=fiber.update(3);release.set()
        await asyncio.wait_for(asyncio.gather(first,second,third),3)
        key=str(injected).lower();result['loading-'+key]=[applied,list(disposed),fiber.state,fiber.effectiveConfig]
        await ctx.fiber.dispose();result['disposed-'+key]=disposed

    ctx=Context();seen=[]
    def plugin(owner,config):
        owner.on('internal/update',lambda candidate:seen.append(['update',owner.fiber.rawConfig,candidate]))
    fiber=ctx.plugin(plugin,0);await fiber
    ctx.on('internal/commit',lambda target,raw:seen.append(['commit',target.rawConfig,raw]))
    fiber.update(1);fiber.update(2,True);result['commit']=seen
    await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_config.mts',
               scope='Candidate resolution, raw/effective identities, commit ordering, retained and loading updates, stale completion rejection.',
               extra_inputs=[ROOT/'dsh/cordis/fiber.py',ROOT/'dsh/cordis/loader.py',ROOT/'dsh/cordis/loader_entry.py',ROOT/'scripts/rc022_config_probe.py',ROOT/'reference/vendor/cordis/src/fiber.ts'])
