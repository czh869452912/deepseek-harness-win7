import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from dsh.cordis import Context
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.domain_impl import DomainFacility
from dsh.workspace.registry_022 import Current022WorkspacePlugin
from scripts.rc022_workspace_default_probe import observe


@pytest_asyncio.fixture
async def host(tmp_path):
    ctx=Context();backend=JsonStorageBackend(str(tmp_path/'medium'))
    ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    headers=[];live=[];gates=[]
    async def listed():return list(headers)
    ctx.provide('sessionPersistence',SimpleNamespace(list=listed))
    ctx.provide('sessions',SimpleNamespace(list=lambda:list(live),get=lambda _:None))
    await ctx.plugin(Current022WorkspacePlugin)
    try:yield SimpleNamespace(ctx=ctx,registry=ctx.workspaceRegistry,headers=headers,live=live,gates=gates)
    finally:
        for gate in gates:gate.set()
        await asyncio.shield(ctx.workspaceRegistry.operation_tail)
        await ctx.fiber.dispose();await facility.close_all();await backend.close()


@pytest.mark.asyncio
async def test_actual_medium_journal_failures_and_default_identity(tmp_path):
    rows=await observe(tmp_path);assert len(rows)==17
    indexed={row['step']:row for row in rows}
    assert indexed['concurrent']['same'] and indexed['concurrent']['lookups']==1
    assert indexed['reopened']['title']=='Renamed'
    assert indexed['deleted']['absent'] and indexed['deleted']['state']['default']
    for name in ('record-rollback','order-delete-rollback','order-state-rollback','delete-state-rollback'):
        assert indexed[name]['error']['name']=='AggregateError'
        assert len(indexed[name]['error']['causes'])==2
        assert indexed[name+'-reopened']['state']['pending'] is None
        assert indexed[name+'-reopened']['state']['records']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['live','history','archive','workspace'])
async def test_nonempty_state_does_not_resolve_default_directory(host,tmp_path,kind):
    if kind=='live':host.live.append(SimpleNamespace(header=dict(id='old')))
    elif kind=='history':host.headers.append(dict(header=dict(id='old')))
    elif kind=='archive':await host.registry._set_state(dict(host.registry._state,archivedSessionIds=['old']))
    else:await host.registry.create(str(tmp_path))
    def forbidden():raise AssertionError('ineligible directory lookup')
    assert await host.registry.initializeDefault(forbidden) is None


@pytest.mark.asyncio
async def test_lookup_failure_relative_path_and_file_leave_initialization_retryable(host,tmp_path):
    async def fail():raise RuntimeError('lookup unavailable')
    with pytest.raises(RuntimeError,match='lookup unavailable'):await host.registry.initializeDefault(fail)
    with pytest.raises(TypeError,match='fully qualified'):await host.registry.initializeDefault(lambda:'relative')
    path=tmp_path/'Workspace';path.write_text('keep',encoding='utf-8')
    with pytest.raises(FileExistsError):await host.registry.initializeDefault(lambda:str(path))
    assert path.read_text(encoding='utf-8')=='keep' and not host.registry.list()
    assert 'defaultWorkspaceId' not in host.registry._state
    path.unlink();path.mkdir();(path/'keep.txt').write_text('keep',encoding='utf-8')
    entity=await host.registry.initializeDefault(lambda:str(path))
    assert entity.title=='Workspace' and (path/'keep.txt').read_text(encoding='utf-8')=='keep'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['live','history'])
async def test_session_arrival_during_directory_preparation_prevents_registration(host,tmp_path,kind):
    def resolve():
        if kind=='live':host.live.append(SimpleNamespace(header=dict(id='arrived')))
        else:host.headers.append(dict(header=dict(id='arrived')))
        return str(tmp_path/'Workspace')
    assert await host.registry.initializeDefault(resolve) is None
    assert (tmp_path/'Workspace').is_dir() and not host.registry.list()
    assert 'defaultWorkspaceId' not in host.registry._state


@pytest.mark.asyncio
async def test_abandoned_initialization_completes_before_queued_delete(host,tmp_path):
    entered=asyncio.Event();release=asyncio.Event();host.gates.append(release)
    async def resolve():entered.set();await release.wait();return str(tmp_path/'Workspace')
    first=host.registry.initializeDefault(resolve);await entered.wait();first.cancel()
    repeated=host.registry.initializeDefault(lambda:(_ for _ in ()).throw(AssertionError('second lookup')))
    release.set();entity=await repeated
    assert await host.registry.delete(entity.id)
    assert await host.registry.initializeDefault(lambda:None) is None
    assert host.registry._state['defaultWorkspaceId']==entity.id
