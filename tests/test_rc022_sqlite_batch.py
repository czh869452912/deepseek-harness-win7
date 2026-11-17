"""SQLite transaction rollback, connection quarantine and real Domain consumer."""
import json
from types import SimpleNamespace

import pytest
from dsh.cordis import Context
from dsh.storage.backend import KvUnitDescriptor
from dsh.storage.error import StorageError
from dsh.storage.storage_sqlite import SqliteStorageBackend
from dsh.storage.domain_impl import DomainFacility
from dsh.storage.domain_spec import define_domain,domain_table
from scripts import rc022_sqlite_batch_probe as probe


@pytest.mark.asyncio
async def test_actual_versions_atomic_mutations_and_cold_reopen(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path);rows=await probe.observe()
    (tmp_path/'sqlite-batch-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    mutations={row['operation']:row for row in rows if row['phase']=='mutation'}
    assert len(rows)==27
    for name in ['abort','rollback','stamp-failed']:
        assert mutations[name]['error'] and mutations[name]['version']==1
        assert list(mutations[name]['state']['tables']['records'])==['a','b']
    assert mutations['batch']['version']==2 and mutations['batch']['state']['tables']['records']=={}
    assert mutations['missing']['version']==mutations['empty']['version']==1


class FaultConnection:
    def __init__(self,db,fault):self.db=db;self.fault=fault
    def __getattr__(self,name):return getattr(self.db,name)
    def execute(self,sql,args=()):
        self.fault(sql);return self.db.execute(sql,args)


@pytest.mark.asyncio
async def test_real_domain_batch_uses_sqlite_transaction_and_reopens(tmp_path):
    ctx=Context();backend=SqliteStorageBackend(dict(path=str(tmp_path/'db')))
    ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));spec=define_domain(name='shape',version=1,tables=dict(t=domain_table(lambda value:value)))
    try:
        domain=await facility.open(spec);table=domain.table('t')
        for key in ['a','b','c']:await table.put(key,key)
        transactions=[];backend.db.set_trace_callback(transactions.append)
        assert await table.deleteMany(['a','c','a','missing'])==2
        assert dict(table.entries())==dict(b='b')
        assert transactions.count('BEGIN IMMEDIATE')==transactions.count('COMMIT')==1
        await domain.close();domain=await facility.open(spec)
        assert dict(domain.table('t').entries())==dict(b='b')
    finally:await facility.close_all();await backend.close();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_begin_does_not_poison_reusable_unit(tmp_path):
    backend=SqliteStorageBackend(dict(path=str(tmp_path/'db')));unit=await backend.kv.open(KvUnitDescriptor('sample',1,['records'],False));await unit.put_record('records','a',1)
    active=[True]
    def fault(sql):
        if active[0] and sql=='BEGIN IMMEDIATE':raise RuntimeError('begin refused')
    unit.db=FaultConnection(backend.db,fault)
    try:
        with pytest.raises(RuntimeError,match='begin refused'):await unit.delete_records('records',['a'])
        assert (await unit.load_all())['tables']['records']==dict(a=1)
        active[0]=False;await unit.deleteRecords('records',['a','a']);assert (await unit.load_all())['tables']['records']=={}
    finally:await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['put','global','batch'])
async def test_failed_rollback_quarantines_all_units_and_openers(tmp_path,operation):
    backend=SqliteStorageBackend(dict(path=str(tmp_path/'db')))
    unit=await backend.kv.open(KvUnitDescriptor('sample',1,['records'],True));await unit.put_record('records','a',1);await unit.close()
    unit=await backend.kv.open(KvUnitDescriptor('sample',2,['records'],True,compatible_versions=[1]));other=await backend.kv.open(KvUnitDescriptor('other',1,['records'],False))
    primary=RuntimeError('stamp failed');rollback=RuntimeError('rollback failed')
    def fault(sql):
        if sql.startswith('UPDATE units SET'):raise primary
        if sql=='ROLLBACK':raise rollback
    unit.db=FaultConnection(backend.db,fault)
    try:
        with pytest.raises(StorageError) as caught:
            if operation=='put':await unit.put_record('records','b',2)
            elif operation=='global':await unit.set_global(dict(new=True))
            else:await unit.delete_records('records',['a'])
        failure=caught.value;assert failure.code=='unknown-state' and failure.cause.errors==[primary,rollback]
        for action in [unit.load_all,other.load_all,lambda:other.put_record('records','x',1),lambda:backend.kv.open(KvUnitDescriptor('new',1,[],False))]:
            with pytest.raises(StorageError) as rejected:await action()
            assert rejected.value is failure
        await unit.close()
        with pytest.raises(StorageError) as closed:await unit.load_all()
        assert closed.value.code=='closed'
    finally:await backend.close()
    backend=SqliteStorageBackend(dict(path=str(tmp_path/'db')))
    try:
        unit=await backend.kv.open(KvUnitDescriptor('sample',1,['records'],True))
        assert (await unit.load_all())==dict(tables=dict(records=dict(a=1)),**{'global':None})
    finally:await backend.close()
