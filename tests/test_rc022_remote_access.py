import asyncio
from types import SimpleNamespace as NS
import pytest
from dsh.cordis import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.typert.remote_access import RemoteAccessService
from scripts.rc022_remote_access_probe import observe, GUEST, ROOM, OTHER


@pytest.mark.asyncio
async def test_decisions_filtering_and_actual_follow_snapshot_deltas():
    rows={row['name']:row for row in await observe()}
    assert rows['bound']['decision']==dict(kind='allow')
    assert rows['every-resource']['decision']==dict(kind='deny',reason='no-allow')
    assert rows['first-refusal']['decision']==dict(kind='deny',reason='first')
    assert rows['later-allow']['decision']==dict(kind='allow')
    assert rows['bindings-failed']['decision']==dict(kind='deny',reason='policy-failed')
    assert rows['condition-failed']['decision']==dict(kind='deny',reason='policy-failed')
    assert rows['explain-failed']['decision']==dict(kind='deny',reason='policy-failed')
    assert rows['bound']['bindingCalls']==1
    assert rows['snapshot-grouping']['snapshot']['grants']==[dict(resource=ROOM,actions=['notes/a','notes/b','notes/z'])]
    assert rows['condition-no-args']['filtered']==[]
    follow=rows['follow']
    assert [frame['type'] for frame in follow['frames']]==['baseline','upsert','upsert','remove']
    assert follow['unaffected'] and follow['followers']==follow['listeners']==0
    assert rows['owner-unload']['listeners']==0


@pytest.mark.asyncio
async def test_failure_reporting_is_once_per_policy_until_invalidation(monkeypatch):
    ctx=Context();await ctx.plugin(RemoteAccessService);access=ctx.remoteAccess;warnings=[]
    monkeypatch.setattr(type(ctx.logger), 'warn', lambda self,*args,**kwargs:warnings.append(args))
    def broken(_):raise ValueError('private fixture failure')
    try:
        access.registerPolicy('guest',NS(bindings=broken))
        request=dict(principal=GUEST,action='notes/read',resources=[ROOM])
        for _ in range(3):assert access.decide(request)['reason']=='policy-failed'
        assert len(warnings)==2
        access.snapshotFor(GUEST)
        assert len(warnings)==2
        access.invalidate(GUEST)
        access.decide(request)
        assert len(warnings)==4
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_policy_owner_withdrawal_updates_stream_and_coalesces_changes():
    ctx=Context();await ctx.plugin(RemoteAccessService);bindings=[]
    class Owner(Plugin):
        inject=['remoteAccess']
        def apply(self, child):
            child.remoteAccess.registerPolicy('guest',dict(bindings=lambda _:bindings))
    owner=await ctx.plugin(Owner);access=ctx.remoteAccess
    invocation=dict(peer=dict(principal=GUEST),request=dict(namespace='remoteAccess',method='follow'))
    controller=AbortController();stream=ctx.extend(dict(invocation=invocation)).remoteAccess.follow(controller.signal)
    try:
        assert (await stream.__anext__())['grants']==[]
        bindings[:]=[dict(resource=ROOM,role=dict(actions=['notes/read']))];access.invalidate()
        bindings[:]=[dict(resource=OTHER,role=dict(actions=['notes/write']))];access.invalidate()
        upsert=await asyncio.wait_for(stream.__anext__(),1)
        assert upsert==dict(type='upsert',grant=dict(resource=OTHER,actions=['notes/write']))
        await owner.dispose()
        assert await asyncio.wait_for(stream.__anext__(),1)==dict(type='remove',resource=OTHER)
        await stream.aclose()
        assert len(controller.signal._listeners)==0
        assert len(access.followers)==0
    finally:
        await stream.aclose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_preaborted_follow_and_grant_actions_are_immutable():
    ctx=Context();await ctx.plugin(RemoteAccessService);access=ctx.remoteAccess
    try:
        access.registerPolicy('guest',dict(bindings=lambda _:[dict(resource=ROOM,role=dict(actions=['notes/read']))]))
        grant=access.snapshotFor(GUEST)['grants'][0]
        with pytest.raises(TypeError):grant['actions'].append('notes/write')
        controller=AbortController();controller.abort(ValueError('stop'))
        with pytest.raises(ValueError,match='stop'):
            await access.follow(controller.signal).__anext__()
        assert len(access.followers)==0
    finally:await ctx.fiber.dispose()
