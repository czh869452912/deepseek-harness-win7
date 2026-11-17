import asyncio
import json

import pytest

from dsh.storage import storage_json as medium
from dsh.storage.backend import KvUnitDescriptor
from dsh.storage.error import StorageError
from scripts.rc022_json_single_probe import observe


@pytest.mark.asyncio
async def test_paired_medium_journeys(tmp_path):
    rows=await observe(tmp_path/'files')
    (tmp_path/'json-single-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==25
    successful={row['op']:row['value'] for row in rows if row['op']!='parse'}
    assert successful['read']['unchanged'] and successful['reopen']['unchanged']
    assert successful['deleteMissing']['unchanged']
    assert successful['put']['disk']['unit']['version']==2
    assert successful['deleteBatch']['snapshot']['tables']['t']==dict(b=2)
    assert successful['concurrentOpen']['secondRejected']


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['put','delete','global'])
async def test_failed_publish_restores_memory_and_preserves_old_bytes(tmp_path,monkeypatch,action):
    path=tmp_path/'shape.json';before=json.dumps(dict(unit=dict(name='shape',version=1),global_='old',tables=dict(t=dict(a=1,b=2,c=3)))).replace('global_','global')
    path.write_text(before,encoding='utf-8');backend=medium.JsonStorageBackend(str(tmp_path))
    unit=await backend.kv.open(KvUnitDescriptor('shape',2,['t'],True,compatible_versions=[1]));snapshot=await unit.load_all()
    calls=[];original=medium.write_atomic
    async def fail(path,content):calls.append(json.loads(content));raise OSError('refused')
    monkeypatch.setattr(medium,'write_atomic',fail)
    try:
        with pytest.raises(OSError,match='refused'):
            if action=='put':await unit.put_record('t','new',4)
            elif action=='delete':await unit.deleteRecords('t',['a','c','a','missing'])
            else:await unit.set_global('new')
        assert len(calls)==1 and await unit.load_all()==snapshot and path.read_text(encoding='utf-8')==before
        monkeypatch.setattr(medium,'write_atomic',original)
        await unit.put_record('t','new',4)
        assert json.loads(path.read_text(encoding='utf-8'))['unit']['version']==2
    finally:await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[False,True])
async def test_close_waits_for_publish_and_keeps_slot_reserved(tmp_path,monkeypatch,failure):
    backend=medium.JsonStorageBackend(str(tmp_path));desc=KvUnitDescriptor('shape',1,['t'])
    unit=await backend.kv.open(desc);started=asyncio.Event();release=asyncio.Event();original=medium.write_atomic
    async def held(path,content):
        started.set();await release.wait()
        if failure:raise OSError('refused')
        await original(path,content)
    monkeypatch.setattr(medium,'write_atomic',held)
    write=asyncio.create_task(unit.put_record('t','a',1));await started.wait()
    close=asyncio.create_task(unit.close());again=asyncio.create_task(unit.close());await asyncio.sleep(0)
    assert not close.done() and not again.done()
    with pytest.raises(ValueError,match='already open'):await backend.kv.open(desc)
    with pytest.raises(StorageError) as caught:await unit.load_all()
    assert caught.value.code=='closed'
    release.set();outcome=await asyncio.gather(write,return_exceptions=True);await asyncio.gather(close,again)
    assert isinstance(outcome[0],OSError) if failure else outcome[0] is None
    reopened=await backend.kv.open(desc)
    assert (await reopened.load_all())['tables']['t']==({} if failure else dict(a=1))
    await backend.close()


@pytest.mark.asyncio
async def test_backend_close_awaits_pending_open_and_rejects_result(tmp_path,monkeypatch):
    backend=medium.JsonStorageBackend(str(tmp_path));desc=KvUnitDescriptor('shape',1,['t']);started=asyncio.Event();release=asyncio.Event()
    original=backend._open_unit
    async def held(descriptor):started.set();await release.wait();return await original(descriptor)
    monkeypatch.setattr(backend,'_open_unit',held)
    opening=asyncio.create_task(backend.kv.open(desc));await started.wait()
    closing=asyncio.create_task(backend.close());again=asyncio.create_task(backend.close());await asyncio.sleep(0)
    assert not closing.done() and not again.done()
    release.set()
    with pytest.raises(StorageError) as caught:await opening
    assert caught.value.code=='closed'
    await asyncio.gather(closing,again)
    assert not backend._open_units and not backend._opening
