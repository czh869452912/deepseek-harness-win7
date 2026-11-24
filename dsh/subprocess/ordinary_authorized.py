"""Canonical ordinary-process object contract over the native Windows owner."""
import asyncio
import math

from dsh.cordis.utils import js_to_string
from dsh.core.cleanup import CleanupPromise
from dsh.core.cancellation import subscribe_abort
from .error import SubprocessError
from .types import SubprocessCollect,SubprocessSpawnSpec,SubprocessStdio
from .local import LocalSubprocessHandle,MAX_TIMER_DELAY_MS


def validate(spec):
    grace=spec.get('graceMs')
    if type(grace) not in (int,float) or not 0<grace<=MAX_TIMER_DELAY_MS or not math.isfinite(grace):
        raise ValueError('subprocess graceMs must be a positive finite number no greater than %s' % MAX_TIMER_DELAY_MS)
    signal=spec.get('signal')
    if signal is not None and signal.aborted:
        reason=getattr(signal,'reason',None)
        try:text=js_to_string(reason) if reason is not None else 'aborted'
        except BaseException:text='aborted'
        error=RuntimeError('aborted before spawn: '+text);error.name='AbortError';raise error
    if not spec.get('argv') or not spec['argv'][0]:
        raise SubprocessError('invalid argv: expected a non-empty program name at argv[0]','SUBPROCESS_INVALID_ARGV')


class OutputReader:
    def __init__(self,reader):self.reader=reader
    def readFrom(self,offset):return self.reader.readFrom(offset).to_dict()


class OrdinaryHandle:
    def __init__(self,raw,batch=None,signal=None):
        self.raw=raw;self.pid=raw.pid
        self.stdin=raw.stdin if batch is None else None
        self.stdout,self.stderr=raw.stdout,raw.stderr
        self.control=None
        self.collected={name:OutputReader(getattr(raw.collected,name)) for name in ('stdout','stderr') if getattr(raw.collected,name) is not None}
        self.release=None
        async def outcome():
            try:return (await asyncio.shield(raw.done)).to_dict()
            finally:
                # Direct process completion may leave detached descendants in
                # its Job. Preserve that result; when the range has exited,
                # join cleanup so ordinary completed jobs expose no stale owner.
                if self.release is not None and not raw._tree_alive():await asyncio.shield(self.release)
        self.done=CleanupPromise(outcome())
        self.detach=subscribe_abort(signal,lambda _:raw.terminate())
        self.writer=None
        if batch is not None and raw.stdin is not None:
            def write():
                try:raw.stdin.write(batch.encode('utf-8'));raw.stdin.flush()
                except (BrokenPipeError,OSError):pass
                finally:raw.stdin.close()
            async def send():await asyncio.get_running_loop().run_in_executor(None,write)
            self.writer=asyncio.create_task(send())
            self.writer.add_done_callback(lambda task:None if task.cancelled() else task.exception())

    def terminate(self):self.raw.terminate()
    def terminate_for_host_exit(self):self.raw.terminate_for_host_exit()
    async def waitForExit(self,signal=None):return await self.raw.wait_for_exit(signal)
    async def wait_for_exit(self,signal=None):return await self.waitForExit(signal)


def spawn(runtime,spec):
    validate(spec)
    from .windows_process import WindowsJobProcess
    stdio=spec['stdio'];batch=stdio['stdin'].get('data') if isinstance(stdio['stdin'],dict) else None
    def mode(value):
        if isinstance(value, dict):
            return SubprocessCollect(value['maxBytes'], value.get('spill'),
                                     text_encoding=value.get('textEncoding', 'utf-8'))
        return value
    native=SubprocessSpawnSpec(spec['argv'],spec['cwd'],SubprocessStdio(
        'pipe' if batch is not None else stdio['stdin'],mode(stdio['stdout']),mode(stdio['stderr'])),
        spec['graceMs'],env=spec.get('env'))
    raw=LocalSubprocessHandle(native,dict(launch=WindowsJobProcess))
    handle=OrdinaryHandle(raw,batch,spec.get('signal'));runtime.live.add(handle)
    async def release():
        try:await asyncio.shield(raw.done)
        except Exception:pass
        finally:handle.detach()
        await raw.wait_for_exit()
        if handle.writer is not None:await handle.writer
        process=getattr(raw,'_proc',None)
        if process is not None:process.close_handles()
        runtime.live.discard(handle)
    task=asyncio.create_task(release())
    handle.release=task
    runtime.ordinary_cleanups.add(task)
    def settled(done):
        if not done.cancelled() and done.exception() is None:
            runtime.ordinary_cleanups.discard(done)
    task.add_done_callback(settled)
    return handle
