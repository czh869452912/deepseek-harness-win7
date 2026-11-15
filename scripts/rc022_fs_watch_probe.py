"""Actual filesystem watching with explicit backend coalescing projection."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.fs.local_current import CurrentFileSystem
    from dsh.core.abort import AbortController
    rows=[];base=WORKSPACE/'native';base.mkdir();fs=CurrentFileSystem(cwd=str(base))
    async def wait_until(predicate):
        for _ in range(500):
            if predicate():return
            await asyncio.sleep(.01)
        raise RuntimeError('watch observation deadline')
    for mode in ('existing','missing'):
        root=base/mode;root.mkdir();path=root/'target';unrelated=root/'unrelated'
        if mode=='existing':path.write_text('initial',encoding='utf-8')
        controller=AbortController();events=[];target=await fs.resolve(str(path));close=await fs.watch(target,lambda *args:events.append('error' if args else 'change'),controller.signal)
        try:
            initial=len(events);unrelated.write_text('unrelated',encoding='utf-8');await asyncio.sleep(.2);isolated=len(events)==initial
            path.write_text('created or updated',encoding='utf-8');await wait_until(lambda:len(events)>initial);observed=len(events)
            await asyncio.sleep(.2);controller.abort();path.write_text('after initialization signal abort',encoding='utf-8');await wait_until(lambda:len(events)>observed)
            await close();closed=len(events);path.write_text('after close',encoding='utf-8');await asyncio.sleep(.2)
            print(json.dumps(dict(mode=mode,events=events)),file=sys.stderr)
            rows.append(dict(name=mode,noInitial=initial==0,unrelatedIgnored=isolated,observed=observed>initial,abortAfterReadyStillObserved=closed>observed,closeQuiescent=len(events)==closed))
        finally:await close()
    root=base/'directory';root.mkdir();controller=AbortController();events=[];close=await fs.watch(await fs.resolve(str(root)),lambda *args:events.append('error' if args else 'change'),controller.signal)
    try:
        (root/'child').write_text('direct',encoding='utf-8');await wait_until(lambda:bool(events));direct=True;directory=root/'nested';directory.mkdir();await asyncio.sleep(.25);count=len(events);(directory/'grandchild').write_text('nested',encoding='utf-8');await asyncio.sleep(.25)
        rows.append(dict(name='directory',direct=direct,nestedIgnored=len(events)==count));print(json.dumps(dict(mode='directory',events=events)),file=sys.stderr)
    finally:await close()
    controller=AbortController();reason=RuntimeError('abort');controller.abort(reason)
    try:await fs.watch(await fs.resolve(str(base/'never')),lambda *_:None,controller.signal)
    except Exception as error:rows.append(dict(name='already-aborted',original=error is reason,noWatcher=not fs.watchers))
    actual_stat=fs.stat;entered=asyncio.get_running_loop().create_future();gate=asyncio.get_running_loop().create_future();controller=AbortController()
    async def stat(*_):entered.set_result(None);return await gate
    fs.stat=stat;pending=asyncio.create_task(fs.watch(await fs.resolve(str(base/'never')),lambda *_:None,controller.signal));await entered;controller.abort(reason);gate.set_result(None)
    try:await pending
    except Exception as error:rows.append(dict(name='metadata-aborted',original=error is reason,noWatcher=not fs.watchers))
    finally:fs.stat=actual_stat
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_fs_watch.mts','Actual Source Chokidar versus Win7 portable metadata polling: existing/missing file watch readiness, unrelated sibling filter, real writes, abort after ready not closing an acquired watch, awaited close quiescence, direct directory entries and ignored nested changes, pre-acquisition abort identity. Raw notifications retained; notification coalescing/timing project to observed or ignored, not exact counts.',[Path(__file__).resolve(),ROOT/'dsh/fs/watch_current.py',ROOT/'dsh/fs/local_current.py'],prepare=prepare)
