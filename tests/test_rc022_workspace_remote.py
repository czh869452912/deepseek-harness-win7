import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from dsh.api.workspace_current import CurrentWorkspaceController
from dsh.core.abort import AbortController
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.remote import RemoteError
from dsh.typert.remote_access import RemoteAccessService
from scripts.rc022_workspace_remote_probe import observe
from tests.test_rc022_workspace_default import host


@pytest_asyncio.fixture
async def remote(host):
    host.live.append(SimpleNamespace(header=dict(id='one',createdAt=0)))
    # The default fixture only needs list(); the command fixture also resolves ids.
    host.ctx.get('sessions').get=lambda identity:next((row for row in host.live if row.header['id']==identity),None)
    await host.ctx.plugin(CurrentTypertRegistry);await host.ctx.plugin(RemoteAccessService)
    fiber=await host.ctx.plugin(CurrentWorkspaceController)
    controller=host.ctx.workspaceController
    try:yield SimpleNamespace(host=host,controller=controller,fiber=fiber)
    finally:
        await asyncio.shield(controller._tail)
        await fiber.dispose()


@pytest.mark.asyncio
async def test_committed_filtered_feed_and_reconnect_against_actual_medium(tmp_path):
    rows=await observe(tmp_path);assert len(rows)==26
    assert rows[0]==dict(type='baseline',value=dict(items=[],archivedSessionIds=[],pinnedSessionIds=[]))
    assert sum(row.get('type')=='replace' for row in rows)==2
    assert [row['failure']['code'] for row in rows if 'failure' in row]==['gateway/bad-request','session/not-found','session/not-found','workspace/session-active']
    assert rows[-1]==dict(step='aborted',ended=True)


@pytest.mark.asyncio
async def test_abandoned_create_serializes_adoption_and_rename(remote,tmp_path,monkeypatch):
    registry=remote.host.registry;controller=remote.controller
    entered=asyncio.Event();release=asyncio.Event();remote.host.gates.append(release)
    original=registry.create
    async def held(path):entered.set();await release.wait();return await original(path)
    monkeypatch.setattr(registry,'create',held)
    first=controller.create(dict(path=str(tmp_path)));await entered.wait();first.cancel()
    second=controller.create(dict(path=str(tmp_path)))
    with pytest.raises(RemoteError,match='non-blank'):
        await asyncio.wait_for(controller.rename(dict(workspaceId='unknown',title='  ')),1)
    release.set();result=await second
    assert not result['created'] and len(registry.list())==1
    renamed=await controller.rename(dict(workspaceId=result['workspace']['workspaceId'],title='  New title  '))
    assert renamed['workspace']['title']=='New title'


@pytest.mark.asyncio
async def test_queue_failure_recovers_and_preserves_structural_remote_error(remote,tmp_path,monkeypatch):
    controller=remote.controller;registry=remote.host.registry;original=registry.resolveByPath
    failure=RemoteError('fixture/failure','original',{})
    async def refuse(path):raise failure
    monkeypatch.setattr(registry,'resolveByPath',refuse)
    with pytest.raises(RemoteError) as caught:await controller.create(dict(path=str(tmp_path)))
    assert caught.value is failure
    monkeypatch.setattr(registry,'resolveByPath',original)
    assert (await controller.create(dict(path=str(tmp_path))))['created']


@pytest.mark.asyncio
async def test_disposal_releases_resource_and_wakes_waiting_followers(remote):
    controller=remote.controller;signal=AbortController();feed=controller.follow(signal.signal)
    await feed.__anext__();waiting=asyncio.create_task(feed.__anext__())
    await asyncio.sleep(0);assert remote.host.ctx.typert.resources.get('workspace') is not None
    await remote.fiber.dispose()
    with pytest.raises(StopAsyncIteration):await asyncio.wait_for(waiting,1)
    assert remote.host.ctx.typert.resources.get('workspace') is None
    assert not controller._followers


@pytest.mark.asyncio
async def test_real_invocation_policy_filters_workspace_and_sessions(remote,tmp_path):
    ctx=remote.host.ctx;controller=remote.controller
    created=await controller.create(dict(path=str(tmp_path)));identity=created['workspace']['workspaceId']
    await controller.pinSession(dict(sessionId='one'))
    allowed=set(['one',identity])
    def bindings(principal):
        return [dict(role=dict(name='viewer',resource=kind,actions=['workspace/follow']),resource=dict(kind=kind,id=item),condition=lambda request:dict(kind='allow') if request['resource']['id'] in allowed else dict(kind='deny',reason='withdrawn')) for kind,item in [('workspace',identity),('session','one')]]
    ctx.remoteAccess.registerPolicy('guest',dict(bindings=bindings))
    invocation=SimpleNamespace(request=dict(namespace='workspace',method='follow',args={}),peer=SimpleNamespace(principal=dict(kind='guest',id='reader')))
    signal=AbortController();feed=ctx.extend(dict(invocation=invocation)).workspaceController.follow(signal.signal)
    try:
        frame=await feed.__anext__();assert frame['value']['pinnedSessionIds']==['one'] and len(frame['value']['items'])==1
        allowed.remove(identity);await controller.rename(dict(workspaceId=identity,title='Revoked'))
        frame=await feed.__anext__();assert frame['type']=='replace' and frame['value']['items']==[]
        assert frame['value']['pinnedSessionIds']==['one']
    finally:await feed.aclose()
