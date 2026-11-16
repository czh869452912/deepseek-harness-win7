"""Packaged ripgrep and incremental process-owned UTF-8 records."""
import asyncio
import codecs
import inspect
from pathlib import Path
import struct
import sys

from dsh.cordis.utils import _js_truthy
from dsh.core.cleanup import CleanupPromise

_resolution = None


def resolve_rg_path():
    global _resolution
    async def resolve():
        if getattr(sys,'frozen',False):
            executable=Path(sys.executable)
            sidecar=executable.with_name(executable.stem+'-rg.exe') if sys.platform=='win32' else Path(str(executable)+'-rg')
            if sidecar.is_file():return str(sidecar)
        directory=Path(__file__).resolve().parents[1]/'fs/tool_fs_search/bin'
        if sys.platform=='win32' and struct.calcsize('P')==4:directory=directory/'x86'
        packaged=directory/('rg.exe' if sys.platform=='win32' else 'rg')
        if not packaged.is_file():raise FileNotFoundError('packaged ripgrep binary is unavailable')
        return str(packaged)
    if _resolution is None:_resolution=CleanupPromise(resolve())
    return _resolution


async def spawn_ripgrep(subprocess,spec):
    executable=await resolve_rg_path()
    handle=subprocess.spawn(dict(spec,argv=[executable,'--no-config']+list(spec['argv'])))
    return await handle if inspect.isawaitable(handle) else handle


async def chunks(stdout):
    decoder=codecs.getincrementaldecoder('utf-8')('replace')
    if callable(getattr(stdout,'setEncoding',None)):stdout.setEncoding('utf8')
    if hasattr(stdout,'__aiter__'):
        async for chunk in stdout:
            yield decoder.decode(chunk) if isinstance(chunk,(bytes,bytearray,memoryview)) else chunk
    else:
        read=getattr(stdout,'read1',None) or stdout.read
        while True:
            chunk=await asyncio.get_running_loop().run_in_executor(None,read,65536)
            if not chunk:break
            yield decoder.decode(chunk) if isinstance(chunk,(bytes,bytearray,memoryview)) else chunk
    tail=decoder.decode(b'',final=True)
    if tail:yield tail


def read_ripgrep_lines(handle,separator,on_line):
    async def run():
        stdout=handle.stdout
        if stdout is None:
            handle.terminate()
            await asyncio.gather(handle.done,handle.waitForExit(),return_exceptions=True)
            raise RuntimeError('ripgrep requires piped stdout')
        stopped=False;completed=False
        async def read():
            nonlocal stopped
            pending=''
            async for chunk in chunks(stdout):
                if stopped:continue
                pending+=chunk
                while separator in pending:
                    line,pending=pending.split(separator,1)
                    if not _js_truthy(on_line(line)):
                        stopped=True;pending='';handle.terminate();break
            if pending and not _js_truthy(on_line(pending)):
                stopped=True;handle.terminate()
        reading=asyncio.ensure_future(read());done=asyncio.ensure_future(handle.done)
        try:
            _,outcome=await asyncio.gather(reading,done)
            completed=True
            return dict(outcome=outcome,stopped=stopped)
        finally:
            if not completed:
                handle.terminate()
                destroy=getattr(stdout,'destroy',None)
                if callable(destroy):destroy()
                elif hasattr(stdout,'fileno'):
                    from dsh.subprocess.local import _cancel_windows_pipe_read
                    _cancel_windows_pipe_read(stdout)
            await asyncio.gather(reading,done,return_exceptions=True)
            try:await handle.waitForExit()
            finally:
                if not hasattr(stdout,'__aiter__'):
                    close=getattr(stdout,'close',None)
                    if callable(close):close()
    return CleanupPromise(run())


resolveRgPath=resolve_rg_path
spawnRipgrep=spawn_ripgrep
readRipgrepLines=read_ripgrep_lines
