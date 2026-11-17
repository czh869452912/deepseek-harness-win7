"""Atomic per-record delete rollback, quarantine and complete write ownership."""
import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio
from dsh.storage.backend import KvUnitDescriptor
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.error import StorageError
from dsh.storage.domain_impl import DomainFacility
from dsh.storage.domain_spec import define_domain,domain_table
from dsh.storage import per_record_json as medium
from scripts import rc022_per_record_batch_probe as probe


@pytest_asyncio.fixture
async def opened(tmp_path):
    backend=JsonStorageBackend(str(tmp_path));descriptor=KvUnitDescriptor('batch',1,['t'],True,layout='per-record')
    unit=await backend.kv.open(descriptor)
    await unit.put_record('t','a',dict(n=1));await unit.put_record('t','b',dict(n=2))
    try:yield backend,descriptor,unit,tmp_path
    finally:await backend.close()


@pytest.mark.asyncio
async def test_legacy_empty_tree_cold_reopen_and_backup(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path);rows=await probe.observe()
    (tmp_path/'per-record-batch-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==10 and all(row.get('legacyUnchanged',True) for row in rows)
    assert all(row['state']['tables']['t']=={} for row in rows if row['phase'] in ('empty','reopened','backup'))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['first','second','sync-once','restore','sync-always','cleanup'])
async def test_batch_failure_preserves_bytes_or_quarantines(opened,monkeypatch,kind):
    backend,descriptor,unit,root=opened;original=medium.rename_document;remove=medium.remove_document;sync=medium.fsync_directory
    before={key:(root/'batch/t'/(key+'.json')).read_bytes() for key in ['a','b']};failure=RuntimeError('staging failed');restore=RuntimeError('restore failed');syncs=[]
    async def rename(source,target):
        if (kind=='first' and target.endswith('a.json.deleting')) or (kind in ('second','restore') and target.endswith('b.json.deleting')):raise failure
        if kind=='restore' and source.endswith('a.json.deleting'):raise restore
        await original(source,target)
    async def synced(path):
        syncs.append(path)
        if kind=='sync-always' or kind=='sync-once' and len(syncs)==1:raise failure
        await sync(path)
    async def cleaned(path):
        if kind=='cleanup':raise RuntimeError('unlink failed')
        await remove(path)
    monkeypatch.setattr(medium,'rename_document',rename);monkeypatch.setattr(medium,'fsync_directory',synced);monkeypatch.setattr(medium,'remove_document',cleaned)
    if kind=='cleanup':
        await unit.deleteRecords('t',['a','b','a']);assert (await unit.load_all())['tables']['t']=={}
        assert sorted(path.name for path in (root/'batch/t').iterdir())==['a.json.deleting','b.json.deleting'];return
    with pytest.raises(Exception) as caught:await unit.delete_records('t',['a','b','a'])
    if kind in ('restore','sync-always'):
        error=caught.value;assert isinstance(error,StorageError) and error.code=='unknown-state'
        assert error.cause.errors==[failure,restore if kind=='restore' else failure]
        for call in [unit.load_all,lambda:unit.put_record('t','c',3),lambda:unit.delete_records('t',[]),lambda:unit.set_global(3),lambda:unit.backupRecord('t','b')]:
            with pytest.raises(StorageError) as rejected:await call()
            assert rejected.value is error
        await unit.close();reopened=await backend.kv.open(descriptor)
        assert (await reopened.load_all())['tables']['t']==(dict(b=dict(n=2)) if kind=='restore' else dict(a=dict(n=1),b=dict(n=2)))
    else:
        assert caught.value is failure
        assert {key:(root/'batch/t'/(key+'.json')).read_bytes() for key in ['a','b']}==before
        assert syncs==[] if kind=='first' else len(syncs)>=1
        monkeypatch.setattr(medium,'rename_document',original);monkeypatch.setattr(medium,'fsync_directory',sync)
        await unit.delete_records('t',['a','b']);assert (await unit.load_all())['tables']['t']=={}


@pytest.mark.asyncio
async def test_close_drains_whole_batch_after_waiter_is_cancelled(opened,monkeypatch):
    backend,descriptor,unit,root=opened;original=medium.rename_document
    entered=[asyncio.Event(),asyncio.Event()];release=[asyncio.Event(),asyncio.Event()]
    async def rename(source,target):
        if target.endswith('.deleting'):
            index=0 if target.endswith('a.json.deleting') else 1;entered[index].set();await release[index].wait()
        await original(source,target)
    monkeypatch.setattr(medium,'rename_document',rename)
    pending=asyncio.create_task(unit.delete_records('t',['a','b']));closing=None
    try:
        await entered[0].wait();pending.cancel()
        with pytest.raises(asyncio.CancelledError):await pending
        closing=asyncio.create_task(unit.close());await asyncio.sleep(0)
        release[0].set();await entered[1].wait();assert not closing.done()
        with pytest.raises(ValueError,match='already open'):await backend.kv.open(descriptor)
        release[1].set();await closing
        unit=await backend.kv.open(descriptor);assert (await unit.load_all())['tables']['t']=={}
    finally:
        for gate in release:gate.set()
        if closing is not None:await closing


@pytest.mark.asyncio
async def test_all_keys_validate_before_staging_and_empty_batch_touches_nothing(opened,monkeypatch):
    unused,descriptor,unit,root=opened;calls=[]
    async def deny(source,target):calls.append([source,target]);raise RuntimeError('unexpected rename')
    monkeypatch.setattr(medium,'rename_document',deny)
    with pytest.raises(ValueError,match='path-safe'):await unit.delete_records('t',['a','../escape'])
    await unit.delete_records('t',[]);assert calls==[]
    assert (await unit.load_all())['tables']['t']==dict(a=dict(n=1),b=dict(n=2))


@pytest.mark.asyncio
async def test_missing_batch_does_not_materialize_or_sync_and_bad_write_allows_bootstrap(tmp_path,monkeypatch):
    backend=JsonStorageBackend(str(tmp_path));descriptor=KvUnitDescriptor('batch',1,['t'],layout='per-record');unit=await backend.kv.open(descriptor)
    async def sync(_):raise AssertionError('unexpected sync')
    monkeypatch.setattr(medium,'fsync_directory',sync)
    try:
        await unit.delete_records('t',[]);await unit.delete_records('t',['missing','missing']);assert list(tmp_path.iterdir())==[]
        with pytest.raises(TypeError):await unit.put_record('t','bad',object())
        assert list(tmp_path.iterdir())==[]
        (tmp_path/'batch.json').write_text(json.dumps(dict(unit=dict(name='batch',version=1),tables=dict(t=dict(saved=7)))),encoding='utf-8')
        assert (await unit.load_all())['tables']['t']==dict(saved=7)
    finally:await backend.close()


@pytest.mark.asyncio
async def test_actual_domain_batch_keeps_empty_tree_authoritative(tmp_path):
    facility=DomainFacility(None,root_dir=str(tmp_path));spec=define_domain(name='shape',version=1,layout='per-record',tables=dict(t=domain_table(lambda value:value)))
    try:
        domain=await facility.open(spec);table=domain.table('t')
        await table.put('a',1);await table.put('b',2)
        assert await table.deleteMany(['a','b','a'])==2 and dict(table.entries())=={}
        await domain.close();domain=await facility.open(spec);assert dict(domain.table('t').entries())=={}
    finally:await facility.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['put','global','backup'])
async def test_close_also_drains_abandoned_document_write_or_backup(opened,monkeypatch,operation):
    backend,descriptor,unit,root=opened;entered=asyncio.Event();release=asyncio.Event()
    write=medium.write_atomic;rename=medium.rename_document
    async def held_write(path,text):entered.set();await release.wait();await write(path,text)
    async def held_rename(source,target):entered.set();await release.wait();await rename(source,target)
    monkeypatch.setattr(medium,'write_atomic',held_write);monkeypatch.setattr(medium,'rename_document',held_rename)
    action=unit.put_record('t','c',3) if operation=='put' else unit.set_global(dict(done=True)) if operation=='global' else unit.backupRecord('t','a')
    pending=asyncio.create_task(action);closing=None
    try:
        await entered.wait();pending.cancel()
        with pytest.raises(asyncio.CancelledError):await pending
        closing=asyncio.create_task(unit.close());await asyncio.sleep(0);assert not closing.done()
        release.set();await closing
        reopened=await backend.kv.open(descriptor);state=await reopened.load_all()
        if operation=='put':assert state['tables']['t']['c']==3
        elif operation=='global':assert state['global']==dict(done=True)
        else:assert state['tables']['t']==dict(b=dict(n=2))
    finally:
        release.set()
        if closing is not None:await closing
