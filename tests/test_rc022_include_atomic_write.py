"""Guard every rename attempt and retain the published snapshot on failures."""
import asyncio
import errno
import os

import pytest

from dsh.cordis import Context
from dsh.cordis.include import Include, StaleWriteError


@pytest.mark.parametrize('asynchronous', [False, True])
def test_guarded_write_rejects_changed_or_missing_file_and_cleans_temporary(tmp_path, asynchronous):
    path=tmp_path/'config.json'
    with path.open('w',encoding='utf-8',newline='') as stream:stream.write('[]\r\n')
    ctx=Context();include=Include(ctx,{'path':str(path)})
    assert include._read_file()['content']=='[]\r\n'
    def write(text, expected):
        if asynchronous:asyncio.run(include._write_text(text,expected))
        else:include._write_text_sync(text,expected)
    with pytest.raises(StaleWriteError):write('[1]','[]\n')
    assert path.read_bytes()==b'[]\r\n'
    path.unlink()
    with pytest.raises(StaleWriteError):write('[1]','[]\r\n')
    assert not path.exists() and not list(tmp_path.glob('.*.tmp'))
    asyncio.run(ctx.fiber.dispose())


@pytest.mark.parametrize('asynchronous', [False, True])
def test_retry_rechecks_expected_and_never_overwrites_external_edit(tmp_path,monkeypatch,asynchronous):
    path=tmp_path/'config.json';path.write_text('[]',encoding='utf-8')
    ctx=Context();include=Include(ctx,{'path':str(path)});calls=[]
    def rename(source,target):
        calls.append((source,target));path.write_text('["external"]',encoding='utf-8')
        raise PermissionError(errno.EACCES,'locked')
    monkeypatch.setattr(os,'replace',rename)
    with pytest.raises(StaleWriteError):
        if asynchronous:asyncio.run(include._write_text('["runtime"]','[]'))
        else:include._write_text_sync('["runtime"]','[]')
    assert len(calls)==1 and path.read_text(encoding='utf-8')=='["external"]'
    assert not list(tmp_path.glob('.*.tmp'))
    asyncio.run(ctx.fiber.dispose())


@pytest.mark.parametrize('asynchronous', [False, True])
def test_failed_write_keeps_old_published_content_and_does_not_leave_partial_temp(tmp_path,monkeypatch,asynchronous):
    path=tmp_path/'config.json';path.write_text('[]',encoding='utf-8')
    ctx=Context();include=Include(ctx,{'path':str(path)});include.content='[]'
    def rename(source,target):raise OSError(errno.ENOSPC,'full')
    monkeypatch.setattr(os,'replace',rename)
    with pytest.raises(OSError):
        if asynchronous:asyncio.run(include._write_file_async([{'id':'new'}]))
        else:include._write_file_sync([{'id':'new'}])
    assert include.content=='[]' and path.read_text(encoding='utf-8')=='[]'
    assert not list(tmp_path.glob('.*.tmp'))
    asyncio.run(ctx.fiber.dispose())


def test_transient_retry_succeeds_and_publishes_only_after_rename(tmp_path,monkeypatch):
    path=tmp_path/'config.json';path.write_text('[]',encoding='utf-8')
    ctx=Context();include=Include(ctx,{'path':str(path)});include.content='[]';real_replace=os.replace;calls=[]
    def rename(source,target):
        assert include.content=='[]'
        calls.append(source)
        if len(calls)==1:raise PermissionError(errno.EACCES,'locked')
        return real_replace(source,target)
    monkeypatch.setattr(os,'replace',rename)
    asyncio.run(include._write_file_async([{'id':'new'}]))
    assert len(calls)==2 and calls[0]==calls[1]
    assert include.content==path.read_text(encoding='utf-8')
    assert not list(tmp_path.glob('.*.tmp'))
    asyncio.run(ctx.fiber.dispose())
