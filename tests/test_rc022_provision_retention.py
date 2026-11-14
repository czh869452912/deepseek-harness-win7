"""Provision identity, isolation and retention through dependent cleanup."""
import asyncio

import pytest

from dsh.cordis import Context, FiberState


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['dispose','restart'])
async def test_isolated_provider_waits_for_dependent_cleanup(action):
    ctx=Context();realm=ctx.isolate('service');events=[]
    disposing=asyncio.Event();release=asyncio.Event();instances=[]
    def provider(owner,config):
        value={'alive':True};instances.append(value)
        owner.isolate('service',realm._isolated_keys['service']).provide('service',value)
        def cleanup():events.append('provider');value['alive']=False
        owner.effect(lambda:cleanup)
    owner=ctx.plugin(provider,{});await owner
    async def cleanup(child):
        disposing.set();await release.wait()
        assert child.service['alive'] is True
        events.append('consumer')
    consumer=realm.inject(['service'],lambda child:lambda:cleanup(child));await consumer
    task=getattr(owner,action)();await asyncio.wait_for(disposing.wait(),2)
    assert events==[] and instances[0]['alive']
    release.set();await asyncio.wait_for(task,2);await consumer
    assert events[:2]==['consumer','provider']
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_own_isolated_provision_does_not_replace_committed_injection():
    ctx=Context();ctx.provide('view','outer');observed=[]
    async def plugin(owner):
        isolated=owner.isolate('view')
        withdraw=isolated.provide('view','inner')
        observed.extend([owner.view,isolated.view])
        child=isolated.plugin(lambda child:observed.append(child.view));await child
        await withdraw()
        observed.extend([owner.view,isolated.view])
    fiber=ctx.inject(['view'],plugin);await fiber
    assert observed==['outer','inner','inner','outer','outer']
    assert set(fiber.committed)=={'view'}
    assert not fiber.provisions
    def private(owner,config):
        owner.isolate('private').provide('private',True)
        with pytest.raises(RuntimeError,match='without inject'):owner.private
    await ctx.plugin(private,{})
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_each_provision_has_distinct_uid_even_on_same_fiber():
    ctx=Context();withdraw=ctx.provide('service','first');first=ctx.reflect._get_impl(ctx,'service')
    applied=[];consumer=ctx.inject(['service'],lambda owner:applied.append(owner.service));await consumer
    first_epoch=consumer.epoch
    await withdraw();await consumer
    assert consumer.state==FiberState.PENDING
    ctx.provide('service','second');second=ctx.reflect._get_impl(ctx,'service');await consumer
    assert first.ctx.fiber is second.ctx.fiber
    assert first.uid!=second.uid and first_epoch!=consumer.epoch
    assert applied==['first','second']
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_retired_provision_waits_only_for_old_retaining_activation():
    ctx=Context();gate=asyncio.Event();started=asyncio.Event();seen=[]
    withdraw=ctx.provide('service','old')
    def plugin(owner):
        value=owner.service;seen.append(value)
        async def cleanup():
            if value=='old':started.set();await gate.wait();assert owner.service=='old'
        return cleanup
    consumer=ctx.inject(['service'],plugin);await consumer
    task=asyncio.ensure_future(withdraw());await started.wait()
    ctx.provide('service','new');gate.set();await asyncio.wait_for(task,2);await consumer
    assert seen==['old','new']
    await ctx.fiber.dispose()
