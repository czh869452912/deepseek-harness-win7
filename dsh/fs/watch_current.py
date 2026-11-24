"""Current watch lifecycle with a portable, shallow metadata polling backend.

LEGAL_ADAPTATION: a Win7/Python 3.8 zero-dependency backend replaces Chokidar.
Notification coalescing and latency are backend details; acquisition, filtering,
errors and awaited release follow the fixed filesystem watch contract.
"""
import asyncio
import os
import stat

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.utils import js_to_string
from dsh.core.cancellation import subscribe_abort
from dsh.core.cleanup import CleanupPromise


class WatchError(RuntimeError):
    name='Error'


class WatchInitAborted(RuntimeError):
    name='AbortError';code='ABORT_ERR'
    def __init__(self,reason):self.cause=reason;super().__init__('The operation was aborted')


class PollingWatcher:
    def __init__(self,root,options,interval=.05,*,exact=None):
        self.root=root;self.options=options;self.interval=interval;self.listeners={};self.closed=False;self.stopped=asyncio.Event();self.closing=None
        self.exact = exact
        self.task=asyncio.create_task(self.run())
        self.task.add_done_callback(lambda task:None if task.cancelled() else task.exception())

    def on(self,event,callback):self.listeners.setdefault(event,[]).append(callback)
    def off(self,event,callback):
        if callback in self.listeners.get(event,[]):self.listeners[event].remove(callback)
    def emit(self,event,*args):
        for callback in list(self.listeners.get(event,[])):callback(*args)

    def snapshot(self):
        entries={}
        def add(path):
            if self.options['ignored'](path):return
            try:info=os.stat(path)
            except FileNotFoundError:return
            directory=stat.S_ISDIR(info.st_mode)
            entries[path]=('directory',info.st_dev,info.st_ino) if directory else ('file',info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        add(self.root)
        if self.exact is not None:
            add(self.exact)
            return entries
        try:
            with os.scandir(self.root) as iterator:
                for entry in iterator:add(os.path.join(self.root,entry.name))
        except (FileNotFoundError,NotADirectoryError):pass
        return entries

    async def run(self):
        try:previous=self.snapshot()
        except Exception as error:self.emit('error',error);return
        self.emit('ready');last_failure=None
        while not self.closed:
            try:await asyncio.wait_for(self.stopped.wait(),self.interval)
            except asyncio.TimeoutError:pass
            if self.closed:break
            try:current=self.snapshot()
            except Exception as error:
                failure=(type(error),str(error))
                if failure!=last_failure:self.emit('error',error)
                last_failure=failure;continue
            last_failure=None
            for path in sorted(previous.keys()|current.keys()):
                if previous.get(path)!=current.get(path):self.emit('all','change',path)
            previous=current

    def close(self):
        if self.closing is None:
            self.closed=True;self.stopped.set()
            async def close():
                try:await self.task
                finally:self.listeners.clear()
            self.closing=CleanupPromise(close())
        return self.closing


async def watch(filesystem,target,changed,signal):
    signal.throwIfAborted();path=os.path.abspath(filesystem.processPath(target));metadata=await filesystem.stat(target,signal);directory=metadata is not None and metadata.type=='directory';signal.throwIfAborted()
    root=path if directory else os.path.dirname(path)
    def ignored(entry):return not directory and os.path.abspath(entry) not in (root,path)
    factory=getattr(filesystem.internals,'watchFactory',None)
    options=dict(ignoreInitial=True,depth=0,ignored=ignored)
    watcher = (factory(root, options) if factory else
               PollingWatcher(root, options, exact=None if directory else path))
    filesystem.watchers.add(watcher)
    ready=asyncio.get_running_loop().create_future()
    def error(value):
        value=value if isinstance(value,Exception) else WatchError(js_to_string(value));changed(value)
        if not ready.done():ready.set_exception(value)
    def prepared():
        if not ready.done():ready.set_result(None)
    def event(_kind,entry):
        if directory or os.path.abspath(entry)==path:changed()
    watcher.on('all',event);watcher.on('error',error);watcher.on('ready',prepared)
    def abort(_):
        if not ready.done():ready.set_exception(WatchInitAborted(signal.reason))
    detach=subscribe_abort(signal,abort)
    closing=[None]
    def close():
        if closing[0] is None:
            async def release():
                try:await await_callback_result(watcher.close())
                finally:filesystem.watchers.discard(watcher)
            closing[0]=CleanupPromise(release())
        return closing[0]
    try:await ready;return close
    except BaseException:
        await close();raise
    finally:
        detach();watcher.off('ready',prepared)
