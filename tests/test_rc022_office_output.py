import asyncio
import os
from pathlib import Path
from types import SimpleNamespace as NS
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.office import output
from dsh.office.errors import OfficeKitError

PDF=b'%PDF-1.7\npreview\n%%EOF\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('data,method,code',[
    (PDF,'pdf',None),(b'\xa5PDF-1.7\n%%EOF\xa0','pdf',None),
    (b'%PDF-1.7\nno trailer','pdf','invalid-output'),(b'%PDF-x.y\n%%EOF','pdf','invalid-output'),
    (b'%PDF-1.7\n%%EOF\x00','pdf','invalid-output'),
    (output.PNG_SIGNATURE+b'payload','png',None),(b'PNG\r\n','png','invalid-output'),
    (b'','output',None),(b'unknown','output',None)])
async def test_complete_bounded_output_and_format_checks(tmp_path,data,method,code):
    path=tmp_path/'output';path.write_bytes(data);signal=AbortController().signal;read=getattr(output,'read_'+method)
    if code:
        with pytest.raises(OfficeKitError) as error:await read(path,len(data),signal)
        assert error.value.code==code
    else:
        assert await read(path,len(data),signal)==data
        path.unlink()  # No open handle or scratch dependency remains.


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation,code', [('grow-limit','output-too-large'),('grow-within','invalid-output'),('shrink','invalid-output'),('directory','invalid-output')])
async def test_opened_metadata_and_sentinel_refuse_changing_outputs_and_close(tmp_path,monkeypatch,mutation,code):
    path=tmp_path/'output';path.write_bytes(PDF);opened=[];original=output._open_output;inspect=output._metadata
    def opening(path):stream=original(path);opened.append(stream);return stream
    def metadata(stream):
        info=inspect(stream)
        if mutation.startswith('grow'):path.write_bytes(PDF+b'extra')
        if mutation=='shrink':path.write_bytes(PDF[:-3])
        return os.stat(tmp_path) if mutation=='directory' else info
    monkeypatch.setattr(output,'_open_output',opening);monkeypatch.setattr(output,'_metadata',metadata)
    limit=len(PDF) if mutation=='grow-limit' else len(PDF)+10
    with pytest.raises(OfficeKitError) as error:await output.read_pdf(path,limit,AbortController().signal)
    assert error.value.code==code and len(opened)==1 and opened[0].closed


@pytest.mark.asyncio
async def test_preabort_oversize_missing_and_directory_output(tmp_path,monkeypatch):
    path=tmp_path/'output';path.write_bytes(PDF);controller=AbortController();failure=RuntimeError('cancel');controller.abort(failure)
    with pytest.raises(RuntimeError) as error:await output.read_output(path,100,controller.signal)
    assert error.value is failure
    with pytest.raises(OfficeKitError) as error:await output.read_output(path,1,AbortController().signal)
    assert error.value.code=='output-too-large'
    with pytest.raises(OfficeKitError) as error:await output.read_output(tmp_path,100,AbortController().signal)
    assert error.value.code=='invalid-output'
    with pytest.raises(FileNotFoundError):await output.read_output(tmp_path/'absent',100,AbortController().signal)


@pytest.mark.asyncio
async def test_waiter_cancellation_does_not_disown_open_read(tmp_path,monkeypatch):
    path=tmp_path/'output';path.write_bytes(PDF);entered=asyncio.Event();release=threading.Event();opened=[];inspect=output._metadata;loop=asyncio.get_running_loop()
    def metadata(stream):
        opened.append(stream);loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):raise RuntimeError('fixture release timed out')
        return inspect(stream)
    monkeypatch.setattr(output,'_metadata',metadata);owned=output.read_output(path,100,AbortController().signal)
    async def wait():return await owned
    waiter=asyncio.create_task(wait())
    try:
        await asyncio.wait_for(entered.wait(),2);waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        assert not owned.task.done() and not opened[0].closed
        release.set();assert await owned==PDF and opened[0].closed
    finally:release.set();await owned


@pytest.mark.asyncio
async def test_signal_cancel_after_read_closes_before_reject(tmp_path,monkeypatch):
    path=tmp_path/'output';path.write_bytes(b'x'*70000);controller=AbortController();failure=RuntimeError('mid-read');opened=[];original=output._open_output
    class Stream:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def fileno(self):return self.stream.fileno()
        def read(self,size):data=self.stream.read(size);controller.abort(failure);return data
    def opening(path):stream=original(path);opened.append(stream);return Stream(stream)
    monkeypatch.setattr(output,'_open_output',opening)
    with pytest.raises(RuntimeError) as error:await output.read_output(path,100000,controller.signal)
    assert error.value is failure and opened[0].closed
