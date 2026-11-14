"""Candidate evaluation and update completion publish only the current config."""
import asyncio

import pytest

from dsh.cordis import Context, FiberState


@pytest.mark.asyncio
async def test_candidate_resolution_keeps_raw_and_effective_identities():
    ctx=Context();applied=[]
    def plugin(owner,config):applied.append(config)
    raw={'value':0};fiber=ctx.plugin(plugin,raw);await fiber
    fiber.ctx.on('internal/config',lambda target,next_fn:dict(next_fn(),resolved=True))
    candidate={'value':1};resolved=fiber.resolveConfig(candidate)
    assert resolved=={'value':1,'resolved':True}
    assert fiber.rawConfig is raw and fiber.config is raw
    assert fiber.effectiveConfig is applied[0]
    assert len(applied)==1
    await fiber.update(candidate)
    assert fiber.rawConfig is candidate
    assert fiber.effectiveConfig is applied[-1]
    assert fiber.effectiveConfig is not resolved
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_retained_updates_ignore_stale_and_rejected_completions():
    ctx=Context();old=asyncio.Future();failed=asyncio.Future();values=[];commits=[]
    def plugin(owner,config):
        values.append(config)
        owner.on('internal/update',lambda candidate:old if candidate==1 else failed if candidate==3 else None)
    ctx.on('internal/commit',lambda fiber,raw:commits.append(raw))
    fiber=ctx.plugin(plugin,0);await fiber
    first=fiber.update(1)
    assert fiber.effectiveConfig==0
    assert fiber.update(2) is None
    old.set_result(None);await first
    assert fiber.effectiveConfig==2
    third=fiber.update(3);failed.set_exception(ValueError('update rejected'))
    with pytest.raises(ValueError,match='update rejected'):await third
    assert fiber.rawConfig==3 and fiber.effectiveConfig==2
    assert commits==[1,2,3] and values==[0]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['raw retention','restart','dispose'])
async def test_old_update_does_not_publish_after_owner_changes(action):
    ctx=Context();gate=asyncio.Future();applied=[]
    def plugin(owner,config):
        applied.append(config);owner.on('internal/update',lambda:gate)
    fiber=ctx.plugin(plugin,{'value':0});await fiber
    old=fiber.update({'value':1})
    if action=='raw retention':fiber.rawConfig={'value':2}
    elif action=='restart':await fiber.restart()
    else:await fiber.dispose()
    gate.set_result(None);await old
    assert fiber.effectiveConfig is applied[-1]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('inject',[False,True])
async def test_latest_update_wins_while_activation_is_loading(inject):
    ctx=Context();ctx.provide('dependency',1);started=asyncio.Event();release=asyncio.Event()
    applied=[];disposed=[]
    async def plugin(owner,config):
        applied.append(config)
        if config==1:started.set();await release.wait()
        owner.effect(lambda:lambda:disposed.append(config))
    plugin.inject=['dependency'] if inject else []
    fiber=ctx.plugin(plugin,0);await fiber
    first=fiber.update(1);await started.wait()
    second=fiber.update(2);third=fiber.update(3);release.set()
    await asyncio.wait_for(asyncio.gather(first,second,third),3)
    assert applied==[0,1,3] and disposed==[0,1]
    assert fiber.state==FiberState.ACTIVE and fiber.effectiveConfig==3
    await ctx.fiber.dispose();assert disposed==[0,1,3]


@pytest.mark.asyncio
async def test_superseded_activation_failure_cannot_fail_latest_update():
    ctx=Context();started=asyncio.Event();release=asyncio.Event();cleanup=[]
    async def plugin(owner,config):
        owner.effect(lambda:lambda:cleanup.append(config))
        if config==1:
            started.set();await release.wait();raise ValueError('superseded activation')
    fiber=ctx.plugin(plugin,1);await started.wait()
    updating=fiber.update(2);release.set();await asyncio.wait_for(updating,3)
    assert cleanup==[1] and fiber.state==FiberState.ACTIVE
    assert fiber.effectiveConfig==2
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_commit_precedes_lifecycle_and_no_save_suppresses_it():
    ctx=Context();seen=[]
    def plugin(owner,config):
        owner.on('internal/update',lambda candidate:seen.append(('update',owner.fiber.rawConfig,candidate)))
    fiber=ctx.plugin(plugin,0);await fiber
    ctx.on('internal/commit',lambda target,raw:seen.append(('commit',target.rawConfig,raw)))
    fiber.update(1);fiber.update(2,no_save=True)
    assert seen==[('commit',0,1),('update',1,1),('update',2,2)]
    await ctx.fiber.dispose()
