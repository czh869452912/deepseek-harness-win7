import asyncio
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace as NS
import uuid

import pytest
import pytest_asyncio

from dsh.office import outputs
from dsh.office.errors import OfficeKitError
from dsh.office.output import read_output
from dsh.core.abort import AbortController


@pytest_asyncio.fixture
async def store(tmp_path,monkeypatch):
    stores=[];warnings=[];io=outputs._io;state=NS(fail=False,block=False,entered=asyncio.Event(),release=asyncio.Event(),removes=0)
    async def controlled(function,*args):
        if function is outputs._remove_tree:
            state.removes+=1
            if state.block:state.entered.set();await state.release.wait()
            if state.fail:raise PermissionError('fixture deletion denied')
        return await io(function,*args)
    monkeypatch.setattr(outputs,'_io',controlled)
    def make(**options):
        value=outputs.OutputStore(dict(dict(root=str(tmp_path/'outputs'),retentionMs=60000,maxBytes=8),**options),warnings.append);stores.append(value);return value
    yield make,state,warnings
    state.fail=False;state.release.set()
    for value in stores:await value.dispose()


@pytest.mark.asyncio
async def test_owner_names_byte_budget_eviction_release_and_refuse_after_disposal(store):
    make,state,warnings=store;value=make();one=Path(await value.save('session/a','../report.pdf',b'12'));two=Path(await value.save('session/b','file',b'3456789'))
    assert one.name=='report.pdf' and one.parent.parent.name==outputs.owner_directory('session/a') and not one.exists()
    assert two.read_bytes()==b'3456789' and value.bytes==7
    with pytest.raises(OfficeKitError) as error:await value.save('x','large',b'x'*9)
    assert error.value.code=='output-too-large'
    await value.release('session/a');assert two.exists();await value.dispose();assert not two.exists() and value.bytes==0
    with pytest.raises(OfficeKitError) as error:await value.save('new','file',b'')
    assert error.value.code=='unavailable' and not warnings


@pytest.mark.asyncio
async def test_expiry_removes_payload_and_disposal_waits_running_release(store):
    make,state,warnings=store;value=make(retentionMs=10);path=Path(await value.save('a','file',b'12'))
    async def gone():
        while path.exists():await asyncio.sleep(.005)
    await asyncio.wait_for(gone(),2);assert value.bytes==0
    value=make();path=Path(await value.save('a','file',b'12'));state.block=True;release=value.release('a');await state.entered.wait()
    disposal=value.dispose();await asyncio.sleep(0);assert not disposal.task.done() and path.exists()
    state.release.set();await asyncio.gather(release,disposal);assert not path.exists() and value.bytes==0


@pytest.mark.asyncio
async def test_failed_delete_remains_in_budget_and_retries_without_double_accounting(store):
    make,state,warnings=store;value=make();path=Path(await value.save('a','file',b'12345'));state.fail=True
    await value.release('a');assert path.exists() and value.bytes==5 and warnings
    with pytest.raises(OfficeKitError) as error:await value.save('b','new',b'6789')
    assert error.value.code=='unavailable' and value.bytes==5
    state.fail=False;state.block=True;release=value.release('a');await state.entered.wait();saved=value.save('b','new',b'6789');state.release.set()
    new=Path(await saved);await release;assert value.bytes==4 and not path.exists() and new.exists()
    await value.dispose();assert value.bytes==0


@pytest.mark.asyncio
async def test_failed_write_cleans_its_directory_and_later_save_continues(store,monkeypatch):
    make,state,warnings=store;value=make();created=[]
    # Exercise the writeOutput finally path with an actual failing low-level write.
    original_open=outputs.os.open
    def opening(path,*args,**kwargs):
        if not created:created.append(str(Path(path).parent));raise PermissionError('fixture write denied')
        return original_open(path,*args,**kwargs)
    monkeypatch.setattr(outputs.os,'open',opening)
    with pytest.raises(PermissionError):await value.save('a','file',b'12')
    assert created and not Path(created[0]).exists() and value.bytes==0
    assert Path(await value.save('a','file',b'12')).read_bytes()==b'12'


@pytest.mark.asyncio
@pytest.mark.parametrize('failures',[1,2])
async def test_missing_parent_write_retries_only_once(store,monkeypatch,failures):
    make,state,warnings=store;value=make();write=outputs._write_output;calls=[]
    def writing(directory,path,data):
        calls.append(directory)
        if len(calls)<=failures:raise FileNotFoundError('fixture parent removed')
        return write(directory,path,data)
    monkeypatch.setattr(outputs,'_write_output',writing)
    if failures==2:
        with pytest.raises(FileNotFoundError):await value.save('a','file',b'12')
    else:assert Path(await value.save('a','file',b'12')).read_bytes()==b'12'
    assert len(calls)==2


@pytest.mark.asyncio
async def test_startup_sweeps_only_expired_generated_real_directories(store,tmp_path):
    make,state,warnings=store;root=tmp_path/'outputs';owner=root/outputs.owner_directory('owner');owner.mkdir(parents=True)
    expired=owner/str(uuid.uuid4());fresh=owner/str(uuid.uuid4());unknown=owner/'leave-me';unknown_owner=root/'session-not-generated'/str(uuid.uuid4())
    for directory in (expired,fresh,unknown,unknown_owner):directory.mkdir(parents=True,exist_ok=True);(directory/'file').write_bytes(b'kept')
    old=time.time()-1000
    for directory in (expired,unknown,unknown_owner):os.utime(str(directory),(old,old))
    value=make(retentionMs=60000);await value.sweep
    assert not expired.exists() and fresh.exists() and unknown.exists() and unknown_owner.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='actual Windows junctions')
async def test_startup_does_not_follow_owner_or_output_junctions(store,tmp_path):
    make,state,warnings=store;root=tmp_path/'outputs';root.mkdir();outside=tmp_path/'outside';outside.mkdir();(outside/'keep').write_bytes(b'keep')
    owner_link=root/outputs.owner_directory('linked');owner=root/outputs.owner_directory('real');owner.mkdir();output_link=owner/str(uuid.uuid4())
    links=[]
    try:
        for link in (owner_link,output_link):
            result=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(outside)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            assert result.returncode==0,result.stdout;links.append(link)
        value=make(retentionMs=1);await value.sweep
        assert all(path.exists() for path in links) and (outside/'keep').read_bytes()==b'keep'
    finally:
        for link in links:os.rmdir(str(link))


@pytest.mark.asyncio
async def test_long_output_path_uses_existing_win7_namespaced_file_calls(store,tmp_path):
    make,state,warnings=store;root=tmp_path/'outputs'/('long-'+'x'*100);value=make(root=str(root),maxBytes=100);path=await value.save('a','report.pdf',b'%PDF-1.7\n%%EOF')
    assert await read_output(path,100,AbortController().signal)==b'%PDF-1.7\n%%EOF';await value.dispose();assert not os.path.exists(outputs._native(path))


@pytest.mark.asyncio
async def test_cancelled_waiter_leaves_store_owned_save_and_release(store):
    make,state,warnings=store;value=make();path=Path(await value.save('a','file',b'12'));state.block=True;owned=value.release('a');await state.entered.wait()
    async def wait():return await owned
    waiter=asyncio.create_task(wait());waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    assert not owned.task.done() and path.exists();state.release.set();await owned;assert not path.exists() and value.bytes==0
