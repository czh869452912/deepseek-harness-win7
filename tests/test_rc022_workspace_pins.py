import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from dsh.cordis import Context
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.domain_impl import DomainFacility
from dsh.workspace.registry_022 import Current022WorkspacePlugin
from scripts.rc022_workspace_pins_probe import observe


@pytest_asyncio.fixture
async def host(tmp_path):
    ctx=Context();backend=JsonStorageBackend(str(tmp_path/'medium'))
    ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    async def listed():return []
    live={identity:SimpleNamespace(header=dict(id=identity,createdAt=0)) for identity in ('one','two')}
    ctx.provide('sessions',SimpleNamespace(get=live.get,list=lambda:list(live.values())))
    persistence=SimpleNamespace(list=listed);ctx.provide('sessionPersistence',persistence)
    fiber=ctx.plugin(Current022WorkspacePlugin);await fiber;gates=[]
    try:yield SimpleNamespace(ctx=ctx,registry=ctx.workspaceRegistry,persistence=persistence,gates=gates)
    finally:
        for gate in gates:gate.set()
        await asyncio.shield(ctx.workspaceRegistry.operation_tail)
        await ctx.fiber.dispose();await facility.close_all();await backend.close()


@pytest.mark.asyncio
async def test_durable_pin_archive_and_schema_observations(tmp_path):
    rows=await observe(tmp_path);assert len(rows)==25
    indexed={row['step']:row for row in rows}
    assert indexed['repeat-pin']['pinned']==['stored','live'] and indexed['repeat-pin']['changes']==0
    assert indexed['active-archive']['error']['activity']==[dict(kind='turn')]
    assert indexed['active-archive']['changes']==0
    assert indexed['stop-archive']['trace']==[['stop','live',['live'],['stored']],['archived','live']]
    assert indexed['cold-reopen']['pinned']==['live'] and indexed['cold-reopen']['archived']==['stored']


@pytest.mark.asyncio
async def test_abandoned_accepted_pin_preserves_fifo_and_later_archive(host,monkeypatch):
    registry=host.registry;entered=asyncio.Event();release=asyncio.Event();host.gates.append(release)
    original=registry._set_state;writes=[]
    async def held(value):
        writes.append(value)
        if len(writes)==1:entered.set();await release.wait()
        await original(value)
    monkeypatch.setattr(registry,'_set_state',held)
    first=registry.pinSession('one');await entered.wait();first.cancel()
    last=registry.pinSession('two');archive=registry.archiveSession('one')
    await asyncio.sleep(0);assert len(writes)==1
    release.set();await last;await archive
    assert [row['pinnedSessionIds'] for row in writes]==[['one'],['two','one'],['two']]
    assert registry.archivedSessionIds==['one']


@pytest.mark.asyncio
async def test_failed_write_does_not_poison_queue_or_publish_pin(host,monkeypatch):
    registry=host.registry;original=registry._set_state;failure=RuntimeError('medium refused');calls=[]
    async def fail_once(value):
        calls.append(value)
        if len(calls)==1:raise failure
        await original(value)
    monkeypatch.setattr(registry,'_set_state',fail_once)
    first=registry.pinSession('one');last=registry.pinSession('two')
    with pytest.raises(RuntimeError) as caught:await first
    assert caught.value is failure
    await last;assert registry.pinnedSessionIds==['two']


@pytest.mark.asyncio
async def test_archive_stops_all_providers_after_commit_and_keeps_archive_on_failure(host):
    registry=host.registry;trace=[]
    def stop(request):
        trace.append(registry.archivedSessionIds);raise RuntimeError('stop refused')
    host.ctx.on('workspace/session-stop',stop)
    host.ctx.on('workspace/session-stop',lambda request:trace.append('other-stop'))
    host.ctx.on('workspace/session-archived',lambda request:trace.append('after-stop'))
    await registry.archiveSession('one',dict(stopActivity=True))
    assert trace==[['one'],'other-stop','after-stop'] and registry.archivedSessionIds==['one']


@pytest.mark.asyncio
async def test_unarchive_admission_failure_preserves_archive_and_can_retry(host):
    registry=host.registry;await registry.archiveSession('one')
    def refuse(*_):raise RuntimeError('admission refused')
    remove=host.ctx.on('workspace/session-unarchiving',refuse)
    with pytest.raises(Exception):await registry.unarchiveSession('one')
    assert registry.archivedSessionIds==['one'];remove()
    await registry.unarchiveSession('one');assert registry.archivedSessionIds==[]


@pytest.mark.asyncio
async def test_persistence_fault_propagates_and_is_not_unknown_session(host):
    failure=RuntimeError('listing unavailable')
    async def listing():raise failure
    host.persistence.list=listing
    with pytest.raises(RuntimeError) as caught:await host.registry.pinSession('missing')
    assert caught.value is failure
    assert not host.registry.pinnedSessionIds
