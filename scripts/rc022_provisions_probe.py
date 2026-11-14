"""Compare provision lifetime and isolation with the unchanged Source."""
import asyncio
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context
    result={}
    for action in ('dispose','restart'):
        ctx=Context();realm=ctx.isolate('service');events=[];disposing=asyncio.Event();release=asyncio.Event();instances=[]
        def plugin(owner,config):
            value={'alive':True};instances.append(value)
            owner.isolate('service',realm._isolated_keys['service']).provide('service',value)
            def cleanup():events.append('provider');value['alive']=False
            owner.effect(lambda:cleanup)
        provider=ctx.plugin(plugin,{});await provider
        async def cleanup(owner):
            disposing.set();await release.wait();events.append('consumer' if owner.service['alive'] else 'broken')
        consumer=realm.inject(['service'],lambda owner:lambda:cleanup(owner));await consumer
        task=getattr(provider,action)();await asyncio.wait_for(disposing.wait(),3)
        waiting=[len(events),instances[0]['alive']];release.set();await task;await consumer
        result[action]=[waiting,list(events),instances[0]['alive']];await ctx.fiber.dispose()
    ctx=Context();observed=[];ctx.provide('view','outer')
    async def plugin(owner):
        isolated=owner.isolate('view');withdraw=isolated.provide('view','inner');observed.extend([owner.view,isolated.view])
        await isolated.plugin(lambda child:observed.append(child.view))
        await withdraw();observed.extend([owner.view,isolated.view])
    fiber=ctx.inject(['view'],plugin);await fiber;private_error=''
    def private(owner,config):
        nonlocal private_error
        owner.isolate('private').provide('private',True)
        try:owner.private
        except RuntimeError as error:private_error=str(error)
    await ctx.plugin(private,{})
    result['isolation']=[observed,list(fiber.committed),len(fiber.provisions),private_error];await ctx.fiber.dispose()
    ctx=Context();applied=[];withdraw=ctx.provide('service','first');first=ctx.reflect._get_impl(ctx,'service')
    consumer=ctx.inject(['service'],lambda owner:applied.append(owner.service));await consumer;epoch=consumer.epoch
    await withdraw();await consumer;pending=consumer.state
    ctx.provide('service','second');second=ctx.reflect._get_impl(ctx,'service');await consumer
    result['identities']=[first.ctx.fiber is second.ctx.fiber,first.uid!=second.uid,epoch!=consumer.epoch,pending,applied]
    await ctx.fiber.dispose()
    ctx=Context();gate=asyncio.Event();started=asyncio.Event();seen=[];withdraw=ctx.provide('service','old')
    def plugin(owner):
        value=owner.service;seen.append(value)
        async def cleanup():
            if value=='old':started.set();await gate.wait();seen.append('retained-'+owner.service)
        return cleanup
    consumer=ctx.inject(['service'],plugin);await consumer
    task=asyncio.ensure_future(withdraw());await started.wait();ctx.provide('service','new');gate.set();await task;await consumer
    result['retired']=seen;await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_provisions.mts',scope='Per-provision identity, isolated own provisions, provider teardown barrier, retired bindings retain only their old dependents.',
               extra_inputs=[ROOT/'dsh/cordis/fiber.py',ROOT/'dsh/cordis/reflect.py',ROOT/'dsh/cordis/context.py',ROOT/'dsh/cordis/loader_isolate.py',Path(__file__).resolve(),ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/fiber.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/reflect.ts'])
