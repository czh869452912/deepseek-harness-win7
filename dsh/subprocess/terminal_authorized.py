"""Canonical Windows terminal seam over the existing Job-owned WinPTY C ABI."""
import asyncio
from collections import deque
import ctypes as c
import os
import msvcrt

from dsh.core.cleanup import CleanupPromise
from dsh.terminal.grapheme import utf8
from dsh.subprocess.windows_inspector import WindowsProcessInspector


def consume(task):
    if not task.cancelled():task.exception()


class WindowsTerminalHandle:
    def __init__(self,raw,released,inspector=None):
        self.raw,self.released=raw,released;self.pid=raw.pid;self.output=self
        self.inspector=inspector or WindowsProcessInspector();self.tracked=[];self.root=None
        try:self.root=next((value for value in self.inspector.snapshot().tree(self.pid) if value['pid']==self.pid),None)
        except Exception:pass
        self.queue=deque();self.bytes=0;self.wake=None;self.space=asyncio.Event();self.space.set()
        self.eof=False;self.error=None;self.closing=None;self.draining=False;self.quiescent=False
        self.activity_key=None;self.activity_revision=0
        raw.defer_output_close=True
        self.pipe=raw.output;self.fd=self.pipe.fileno();self.pipe_handle=msvcrt.get_osfhandle(self.fd)
        self.peek=c.WinDLL('kernel32',use_last_error=True).PeekNamedPipe
        self.peek.argtypes=[c.c_void_p,c.c_void_p,c.c_ulong,c.c_void_p,c.POINTER(c.c_ulong),c.c_void_p];self.peek.restype=c.c_int
        self.reader=asyncio.ensure_future(self.read());self.reader.add_done_callback(consume)
        async def outcome():return (await asyncio.shield(raw.done)).to_dict()
        self.done=asyncio.ensure_future(outcome());self.done.add_done_callback(consume)

    def notify(self):
        if self.wake is not None and not self.wake.done():self.wake.set_result(None)

    def available(self):
        count=c.c_ulong()
        if not self.peek(self.pipe_handle,None,0,None,c.byref(count),None):
            error=c.get_last_error()
            if error in (109,232,233):return -1
            raise c.WinError(error)
        return min(count.value,65536)

    async def read(self):
        try:
            while True:
                if not self.draining and self.bytes>=262144:
                    self.space.clear();await self.space.wait();continue
                size=self.available()
                if size==0:await asyncio.sleep(.005);continue
                chunk=os.read(self.fd,size) if size>0 else b''
                if not chunk:break
                self.queue.append(chunk);self.bytes+=len(chunk);self.notify();await asyncio.sleep(0)
        except Exception as error:self.error=error
        finally:self.eof=True;self.pipe.close();self.raw.output=None;self.notify()

    def __aiter__(self):return self

    async def __anext__(self):
        while True:
            if self.queue:
                chunk=self.queue.popleft();self.bytes-=len(chunk);self.space.set();return chunk
            if self.error is not None:raise self.error
            if self.eof:raise StopAsyncIteration
            self.wake=asyncio.get_running_loop().create_future()
            try:await self.wake
            finally:self.wake=None

    async def write(self,data):
        # Normalize explicit UTF-16 pairs/lone surrogates at the same Buffer
        # boundary as the Source's UTF-8 pipe; ordinary text remains identical.
        await self.raw.write(utf8(data).decode('utf-8'))

    async def resize(self,cols,rows):await self.raw.resize(cols,rows)

    def descendants(self,observed):
        tree=observed.tree(self.pid);root=next((value for value in tree if value['pid']==self.pid),None)
        verified=self.root is not None and root is not None and root['started']==self.root['started']
        members={str(value['pid'])+':'+value['started']:value for value in self.tracked+(tree if verified else []) if value['pid']!=self.pid}
        self.tracked=[value for value in members.values() if observed.alive(value)]
        return self.tracked

    async def inspectForeground(self):
        self.descendants(self.inspector.snapshot())
        return dict(processGroupId=self.pid,inputWaiting=False)

    async def inspectActivity(self):
        state='idle' if self.quiescent else 'unknown'
        if not self.quiescent:
            try:
                if self.descendants(self.inspector.snapshot()):state='busy'
            except Exception:state='unknown'
        key='0:'+state
        if key!=self.activity_key:self.activity_key=key;self.activity_revision+=1
        return dict(state=state,revision=self.activity_revision)

    async def signalForeground(self,signal):
        foreground=await self.inspectForeground()
        if signal=='SIGKILL':raise RuntimeError('refusing to SIGKILL the terminal shell; terminate the terminal session instead')
        if signal=='SIGINT':await self.raw.write('\x03');return foreground['processGroupId']
        if signal in ('SIGTSTP','SIGHUP'):
            raise RuntimeError('signal '+signal+' is unsupported on Windows; only SIGINT, SIGTERM, and SIGKILL are available')
        if signal!='SIGTERM':raise ValueError('Unsupported terminal signal: '+signal)
        # Source Windows pseudo-group SIGTERM is taskkill /T without /F.
        # The final hard-stop remains the pre-owned WinPTY Job, not PID lookup.
        from dsh.subprocess.local import taskkill_process_tree
        async with self.raw._write_lock:
            signaling=asyncio.get_running_loop().run_in_executor(None,taskkill_process_tree,self.pid,False)
            try:await asyncio.shield(signaling)
            except asyncio.CancelledError:
                await asyncio.gather(signaling,return_exceptions=True);raise
        return foreground['processGroupId']

    def terminate_for_host_exit(self):self.raw.terminate_for_host_exit()

    def terminate(self):
        if self.closing is None:
            async def cleanup():
                try:
                    await self.raw.terminate();self.draining=True;self.space.set();await asyncio.shield(self.reader)
                    self.quiescent=True;self.released(self)
                except Exception:self.closing=None;raise
            self.closing=CleanupPromise(cleanup())
        return self.closing
