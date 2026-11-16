"""Target-scoped invalidations with generation-owned asynchronous watcher close."""
import asyncio
from collections import deque

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.typert.artifact import UNDEFINED
from dsh.typert.remote import RemoteError
from dsh.typert.stores import field


def throw(value):
    raise value if isinstance(value,BaseException) else ThrownValueError(value)


class ChangeFollower:
    def __init__(self,release):
        self.release=release;self.controller=AbortController();self.initialized=asyncio.get_running_loop().create_future()
        self.error=UNDEFINED;self.queue=deque();self.wake=asyncio.Event();self.closed=False;self.closing=None

    def push(self,observed):
        if not self.closed:self.queue.append(observed);self.wake.set()

    def close(self):
        if self.closing is None:
            self.closed=True
            async def close():
                try:
                    unwatch=await asyncio.shield(self.initialized)
                    if unwatch is not None:await unwatch()
                finally:self.release()
            self.closing=CleanupPromise(close());self.controller.abort();self.wake.set()
        return self.closing

    def fail(self,error):
        self.error=error;self.controller.abort()

    async def read(self):
        while not self.closed:
            if self.queue:yield self.queue.popleft();continue
            self.wake.clear();await self.wake.wait()
        if self.error is not UNDEFINED:throw(self.error)


class WorkspaceChangeFeed:
    def __init__(self,ctx):
        self.ctx=ctx;self.followers=set()
        ctx.on('fs/observed',self.observed)
        ctx.effect(lambda:self.close,'workspace-files.changes')

    def observed(self,target,observation=None,*_):
        for follower in tuple(self.followers):follower.push((target,observation))

    async def close(self):
        await asyncio.gather(*(follower.close() for follower in tuple(self.followers)))
        self.followers.clear()

    async def follow(self,workspace_root,path,caller):
        caller.throwIfAborted();combined=AbortController();detach=[]
        def release():
            for remove in detach:remove()
            self.followers.discard(follower)
        follower=ChangeFollower(release)
        for source in (caller,follower.controller.signal):detach.append(source.add_listener('abort',lambda reason:combined.abort(reason)))
        signal=combined.signal
        def cancel(_):
            close=follower.close()
            def report(done):
                if not done.cancelled() and done.exception() is not None:self.ctx.logger.error(done.exception())
            close.add_done_callback(report)
        detach.append(signal.add_listener('abort',cancel));self.followers.add(follower)
        unwatch=None
        fs=self.ctx.get('fs')
        async def resolve(value,options):
            try:return await fs.resolve(value,options)
            except Exception:
                if signal.aborted:return None
                raise
        try:
            root=await resolve(workspace_root,dict(signal=signal))
            if root is None or signal.aborted or follower.closed:return
            target=await resolve(path,dict(cwd=workspace_root,signal=signal))
            if target is None or signal.aborted:return
            async def stat():
                try:info=await fs.stat(target,signal)
                except Exception:
                    if signal.aborted:return None
                    raise
                if field(info,'type')=='directory' and not fs.contains(root,target):
                    raise RemoteError('workspace-file/outside-workspace','Directory is outside the workspace',dict(path=path))
                return info
            await stat()
            if signal.aborted:return
            def changed(error=UNDEFINED):
                if error is not UNDEFINED:follower.fail(error)
                elif not follower.closed:follower.push((target,None))
            try:
                unwatch=await fs.watch(target,changed,signal)
                if follower.error is not UNDEFINED:throw(follower.error)
            except Exception as error:
                if signal.aborted and follower.error is UNDEFINED:return
                failure=follower.error if follower.error is not UNDEFINED and follower.error is not None else error
                if isinstance(failure,ThrownValueError):failure=failure.value
                message=getattr(failure,'message',str(failure)) if isinstance(failure,Exception) else js_to_string(failure)
                raise RemoteError('workspace-file/watch-unsupported',message,dict(path=path)) from None
            follower.initialized.set_result(unwatch)
            if signal.aborted:return
            yield dict(kind='ready')
            reader=follower.read()
            try:
                async for observed,_ in reader:
                    if field(observed,'targetKey')!=field(target,'targetKey'):continue
                    info=await stat()
                    if signal.aborted:return
                    change=dict(absolutePath=fs.processPath(target))
                    change.update(dict(version=field(info,'version',UNDEFINED)) if info is not None else dict(absent=True))
                    yield dict(kind='change',change=change)
            finally:await reader.aclose()
        finally:
            if not follower.initialized.done():follower.initialized.set_result(unwatch)
            await follower.close()
