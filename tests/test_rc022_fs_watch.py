import asyncio
import os

import pytest

from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.fs.local_current import CurrentFileSystem
from dsh.fs.watch_current import WatchInitAborted
from scripts import rc022_fs_watch_probe as probe


class ControlledWatcher:
    def __init__(self,root,options):
        self.root=root;self.options=options;self.listeners={};self.closed=False;self.gate=asyncio.get_running_loop().create_future();self.closing=None
    def on(self,event,callback):self.listeners.setdefault(event,[]).append(callback)
    def off(self,event,callback):self.listeners[event].remove(callback)
    def emit(self,event,*args):
        for callback in list(self.listeners.get(event,[])):callback(*args)
    def close(self):
        if self.closing is None:
            async def close():await self.gate;self.closed=True
            self.closing=CleanupPromise(close())
        return self.closing


async def fixture(tmp_path,kind='missing'):
    fs=CurrentFileSystem(cwd=str(tmp_path));path=tmp_path/'target'
    if kind=='directory':path.mkdir()
    elif kind=='file':path.write_text('data',encoding='utf-8')
    target=await fs.resolve(str(path));acquired=asyncio.get_running_loop().create_future();events=[];controller=AbortController()
    def factory(root,options):
        watcher=ControlledWatcher(root,options);acquired.set_result(watcher);return watcher
    fs.internals.watchFactory=factory
    pending=asyncio.create_task(fs.watch(target,lambda *args:events.append(args),controller.signal));watcher=await acquired
    return fs,target,watcher,controller,events,pending


@pytest.mark.asyncio
async def test_actual_file_directory_and_cancellation_observations(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,'WORKSPACE',tmp_path);rows={row['name']:row for row in await probe.observe()}
    for kind in ('existing','missing'):assert all(value for key,value in rows[kind].items() if key!='name')
    assert rows['directory']['direct'] and rows['directory']['nestedIgnored']
    assert rows['already-aborted']['original'] and rows['metadata-aborted']['original']


@pytest.mark.asyncio
async def test_exact_file_watch_does_not_enumerate_siblings(tmp_path, monkeypatch):
    fs = CurrentFileSystem(cwd=str(tmp_path))
    target = await fs.resolve('target')
    events = asyncio.Queue()
    controller = AbortController()
    close = await fs.watch(target, lambda error=None: events.put_nowait(error), controller.signal)

    def unexpected_scan(_directory):
        raise AssertionError('an exact file watch must not enumerate the directory')

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, 'scandir', unexpected_scan)
            (tmp_path / 'target').write_text('created', encoding='utf-8')
            assert await asyncio.wait_for(events.get(), 2) is None
            (tmp_path / 'target').unlink()
            assert await asyncio.wait_for(events.get(), 2) is None
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['file','missing','directory'])
async def test_waits_for_ready_filters_events_and_awaits_close(tmp_path,kind):
    fs,target,watcher,controller,events,pending=await fixture(tmp_path,kind)
    try:
        assert not pending.done() and watcher.options['ignoreInitial'] and watcher.options['depth']==0
        root=target.targetKey if kind=='directory' else os.path.dirname(target.targetKey)
        assert watcher.root==root and not watcher.options['ignored'](target.targetKey)
        other=os.path.join(root,'unrelated');assert watcher.options['ignored'](other)==(kind!='directory')
        watcher.emit('ready');close=await pending
        watcher.emit('all','change',other)
        assert events==([()] if kind=='directory' else [])
        watcher.emit('all','change',target.targetKey);assert events[-1]==()
        error=RuntimeError('failed');watcher.emit('error',error);watcher.emit('error','unavailable')
        assert events[-2][0] is error and str(events[-1][0])=='unavailable'
        assert not controller.signal._listeners
        first=close();assert first is close() and watcher in fs.watchers and not watcher.closed
        async def wait():return await first
        waiting=asyncio.create_task(wait());await asyncio.sleep(0);waiting.cancel()
        with pytest.raises(asyncio.CancelledError):await waiting
        watcher.gate.set_result(None);await first
        assert watcher.closed and not fs.watchers
    finally:
        if not watcher.gate.done():watcher.gate.set_result(None)
        if not pending.done():watcher.emit('ready')
        await watcher.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['abort','error','cancel-waiter'])
async def test_initialization_failure_joins_acquired_watcher_before_returning(tmp_path,mode):
    fs,target,watcher,controller,events,pending=await fixture(tmp_path);error=RuntimeError('failure')
    try:
        if mode=='abort':controller.abort(error)
        elif mode=='error':watcher.emit('error',error)
        else:pending.cancel()
        for _ in range(5):await asyncio.sleep(0)
        assert not pending.done() and not watcher.closed
        watcher.gate.set_result(None)
        if mode=='cancel-waiter':
            with pytest.raises(asyncio.CancelledError):await pending
        elif mode=='abort':
            with pytest.raises(WatchInitAborted) as caught:await pending
            assert caught.value.cause is error and caught.value.code=='ABORT_ERR' and not events
        else:
            with pytest.raises(RuntimeError) as caught:await pending
            assert caught.value is error and events==[(error,)]
        assert watcher.closed and not fs.watchers and not controller.signal._listeners
    finally:
        if not watcher.gate.done():watcher.gate.set_result(None)
        await watcher.close()


@pytest.mark.asyncio
async def test_backend_initialization_error_closes_and_is_reported_once(tmp_path,monkeypatch):
    from dsh.fs.watch_current import PollingWatcher
    fs=CurrentFileSystem(cwd=str(tmp_path));target=await fs.resolve('target');events=[];controller=AbortController();original=PermissionError('snapshot unavailable')
    def fail(_):raise original
    monkeypatch.setattr(PollingWatcher,'snapshot',fail)
    with pytest.raises(PermissionError) as caught:await fs.watch(target,lambda *args:events.append(args),controller.signal)
    assert caught.value is original and events==[(original,)]
    assert not fs.watchers and not controller.signal._listeners
