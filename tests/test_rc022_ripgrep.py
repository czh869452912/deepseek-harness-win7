import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.cordis import Context
from dsh.core.cleanup import CleanupPromise
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.util import ripgrep


class Stream:
    def __init__(self,chunks=(),blocked=False,failure=None):
        self.chunks=list(chunks);self.blocked=blocked;self.failure=failure;self.closed=asyncio.Event();self.encoding=None
    def setEncoding(self,encoding):self.encoding=encoding
    def destroy(self):self.closed.set()
    async def __aiter__(self):
        for chunk in self.chunks:yield chunk
        if self.failure:raise self.failure
        if self.blocked:await self.closed.wait()


def handle(stream,failure=None,cleanup=None):
    state=dict(terminated=0,waited=0)
    async def done():
        if failure:raise failure
        return dict(exitCode=0,signal=None)
    async def wait():
        state['waited']+=1
        if cleanup is not None:await cleanup.wait()
        return True
    def terminate():state['terminated']+=1
    return SimpleNamespace(stdout=stream,done=CleanupPromise(done()),terminate=terminate,waitForExit=wait,state=state)


@pytest.mark.asyncio
@pytest.mark.parametrize('chunks,separator,expected',[
    ([b'\xe9',b'\x9b\xaa\0two\0tail'],'\0',['雪','two','tail']),
    ([b'one\ntwo\n',b'three\n'],'\n',['one','two','three']),
    ([b'\xff\0a\nb\0'],'\0',['�','a\nb']),
    ([],'\n',[]),([b'\n'],'\n',['']),([b'\xe9'],'\0',['�'])])
async def test_incremental_utf8_framing_final_tail_and_empty_records(chunks,separator,expected):
    stream=Stream(chunks);child=handle(stream);lines=[]
    result=await ripgrep.read_ripgrep_lines(child,separator,lambda line:lines.append(line) or True)
    assert result==dict(outcome=dict(exitCode=0,signal=None),stopped=False)
    assert lines==expected and child.state==dict(terminated=0,waited=1) and stream.encoding=='utf8'


@pytest.mark.asyncio
@pytest.mark.parametrize('chunks',[[b'one\ntwo\n',b'three\n'],[b'last']])
async def test_stopping_drains_buffered_output_and_stops_callbacks(chunks):
    child=handle(Stream(chunks));lines=[]
    result=await ripgrep.read_ripgrep_lines(child,'\n',lambda line:lines.append(line) or False)
    assert result['stopped'] and len(lines)==1 and child.state==dict(terminated=1,waited=1)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['missing','callback','stream','provider'])
async def test_failures_preserve_reason_and_join_cleanup(mode):
    failure=RuntimeError(mode);stream=None if mode=='missing' else Stream([b'line\n'],blocked=mode=='provider',failure=failure if mode=='stream' else None)
    child=handle(stream,failure if mode in ('missing','provider') else None)
    def consume(line):
        if mode=='callback':raise failure
        return True
    with pytest.raises(RuntimeError) as error:await asyncio.wait_for(ripgrep.read_ripgrep_lines(child,'\n',consume),3)
    if mode=='missing':assert 'requires piped stdout' in str(error.value)
    else:assert error.value is failure
    assert child.state==dict(terminated=1,waited=1)
    if stream is not None:assert stream.closed.is_set()


@pytest.mark.asyncio
async def test_range_exit_is_a_barrier_and_cancelled_python_waiter_does_not_disown_it():
    cleanup=asyncio.Event();child=handle(Stream([b'line\n']),cleanup=cleanup)
    result=ripgrep.read_ripgrep_lines(child,'\n',lambda _:True)
    async def waiter():return await result
    waiting=asyncio.create_task(waiter())
    for _ in range(30):
        if child.state['waited']:break
        await asyncio.sleep(0)
    assert child.state['waited']==1 and not result.task.done()
    waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)
    assert not result.task.done();cleanup.set()
    assert (await result)['outcome']['exitCode']==0


@pytest.mark.asyncio
async def test_native_binary_pipe_is_closed_after_complete_read():
    stream=io.BytesIO(b'one\0two');child=handle(stream);lines=[]
    await ripgrep.read_ripgrep_lines(child,'\0',lambda line:lines.append(line) or True)
    assert stream.closed and lines==['one','two']


@pytest.mark.asyncio
async def test_native_pipe_closes_even_if_provider_range_cleanup_fails():
    stream=io.BytesIO(b'line\n');child=handle(stream);failure=RuntimeError('cleanup failed')
    async def fail():raise failure
    child.waitForExit=fail
    with pytest.raises(RuntimeError) as error:await ripgrep.read_ripgrep_lines(child,'\n',lambda _:True)
    assert error.value is failure and stream.closed


@pytest.mark.asyncio
async def test_packaged_resolution_is_cached_and_ignores_environment_fallbacks(monkeypatch):
    monkeypatch.setattr(ripgrep,'_resolution',None);monkeypatch.setenv('DSH_RG_PATH','untrusted.exe');monkeypatch.setenv('PATH','')
    path=await ripgrep.resolve_rg_path();assert Path(path).is_file() and Path(path).name=='rg.exe'
    assert ripgrep.resolve_rg_path() is ripgrep.resolve_rg_path()
    monkeypatch.setattr(ripgrep,'_resolution',None);monkeypatch.setattr(Path,'is_file',lambda _:False)
    failed=ripgrep.resolve_rg_path()
    with pytest.raises(FileNotFoundError):await failed
    monkeypatch.setattr(Path,'is_file',lambda _:True)
    assert ripgrep.resolve_rg_path() is failed
    with pytest.raises(FileNotFoundError):await ripgrep.resolve_rg_path()


@pytest.mark.asyncio
async def test_spawn_prepends_no_config_and_preserves_other_fields(monkeypatch):
    monkeypatch.setattr(ripgrep,'_resolution',None);calls=[];token=object()
    runtime=SimpleNamespace(spawn=lambda spec:calls.append(spec) or token)
    spec=dict(argv=['--files'],cwd='/workspace',stdio=dict(stdin='ignore',stdout='pipe',stderr=dict(maxBytes=20)),graceMs=3,env=dict(TEST='value'),signal=object())
    assert await ripgrep.spawn_ripgrep(runtime,spec) is token
    assert calls==[dict(spec,argv=[await ripgrep.resolve_rg_path(),'--no-config','--files'])] and spec['argv']==['--files']


@pytest.mark.skipif(os.name!='nt',reason='canonical Win7 process provider')
@pytest.mark.asyncio
async def test_actual_packaged_rg_stream_owned_by_native_process_range(tmp_path,monkeypatch):
    monkeypatch.setattr(ripgrep,'_resolution',None);(tmp_path/'file.txt').write_bytes(b'value');(tmp_path/'雪.txt').write_bytes(b'snow')
    ctx=Context();await ctx.plugin(AuthorizedLocalSubprocessRuntime);lines=[]
    try:
        child=await ripgrep.spawn_ripgrep(ctx.subprocess,dict(argv=['--files','--null','--sort=path'],cwd=str(tmp_path),stdio=dict(stdin='ignore',stdout='pipe',stderr=dict(maxBytes=1000)),graceMs=5))
        result=await ripgrep.read_ripgrep_lines(child,'\0',lambda line:lines.append(line) or True)
        assert result==dict(outcome=dict(exitCode=0,signal=None),stopped=False) and lines==['file.txt','雪.txt']
        await asyncio.wait_for(asyncio.gather(*ctx.subprocess.ordinary_cleanups),3)
        assert not ctx.subprocess.live and child.stdout.closed
    finally:await ctx.fiber.dispose()
