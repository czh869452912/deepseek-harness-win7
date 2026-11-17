"""Current Workspace committed feed and resource-filtered reconnect observations."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
FILES=None


async def observe(files=None):
    from dsh.cordis import Context
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.domain_impl import DomainFacility
    from dsh.workspace.registry_022 import Current022WorkspacePlugin
    from dsh.api.workspace_current import CurrentWorkspaceController
    from dsh.core.abort import AbortController
    from dsh.typert.current import CurrentTypertRegistry
    files=Path(files or FILES);ctx=Context();rows=[];aliases={};hidden=set();live={identity:SimpleNamespace(header=dict(id=identity,createdAt=0)) for identity in ('shared','secret')}
    backend=JsonStorageBackend(str(files/'native'));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    async def listed():return []
    ctx.provide('sessionPersistence',SimpleNamespace(list=listed));ctx.provide('sessions',SimpleNamespace(get=live.get,list=lambda:list(live.values())))
    ctx.provide('remoteAccess',SimpleNamespace(allows=lambda resource:resource['id'] not in hidden))
    await ctx.plugin(Current022WorkspacePlugin);await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(CurrentWorkspaceController)
    controller=ctx.workspaceController;abort=AbortController();feed=controller.follow(abort.signal)
    def project(value):
        if isinstance(value,list):return [project(row) for row in value]
        if isinstance(value,dict):return {key:project(item) for key,item in value.items() if key not in ('path','createdAt','updatedAt')}
        return aliases.get(value,value) if isinstance(value,str) else value
    async def take():rows.append(project(await asyncio.wait_for(feed.__anext__(),2)))
    async def error(method,request):
        try:await getattr(controller,method)(request)
        except Exception as exc:rows.append(dict(step=method,failure=project(exc.failure)))
        else:raise AssertionError('expected Remote failure')
    try:
        await take()
        for name in ('first','second'):
            path=files/name;path.mkdir(exist_ok=True)
            result=await controller.create(dict(path=str(path)));aliases[result['workspace']['workspaceId']]=name
            rows.append(dict(step='create',created=result['created'],title=result['workspace']['title']));await take();await take()
        ids={name:identity for identity,name in aliases.items()}
        rows.append(dict(step='reuse',created=(await controller.create(dict(path=str(files/'first'))))['created']))
        await controller.pinSession(dict(sessionId='shared'));await take()
        await controller.pinSession(dict(sessionId='secret'));await take()
        await feed.aclose();hidden.add('secret');feed=controller.follow(abort.signal);await take()
        await controller.archiveSession(dict(sessionId='secret'));await take();await take()
        await error('pinSession',dict(sessionId='secret'));await error('pinSession',dict(sessionId='missing'));await error('archiveSession',dict(sessionId='missing'))
        remove=ctx.on('workspace/session-activity',lambda request,next_fn:[dict(kind='turn')])
        await error('archiveSession',dict(sessionId='shared'));remove()
        await controller.unarchiveSession(dict(sessionId='secret'));await take()
        hidden.add(ids['first']);await controller.rename(dict(workspaceId=ids['first'],title='revoked'));await take()
        hidden.remove(ids['first']);await controller.rename(dict(workspaceId=ids['first'],title='restored'));await take()
        hidden.add(ids['second']);await controller.insertBefore(dict(workspaceId=ids['first'],beforeWorkspaceId=ids['second']));await take()
        await controller.delete(dict(workspaceId=ids['second']));await take()
        await controller.delete(dict(workspaceId=ids['first']));await take();await take()
        await feed.aclose();feed=controller.follow(abort.signal);await take()
        abort.abort()
        try:await feed.__anext__()
        except StopAsyncIteration:rows.append(dict(step='aborted',ended=True))
    finally:
        await feed.aclose();await ctx.fiber.dispose();await facility.close_all();await backend.close()
    return rows


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_remote.mts','Actual JSON Workspace command/feed: complete baseline, committed order, pins and archive, stable errors, filtered Sessions, access revocation replace/reappearance, filtered deletion and reconnect/abort.',[Path(__file__).resolve(),ROOT/'dsh/api/workspace_current.py',ROOT/'dsh/workspace/registry_022.py'],prepare=prepare)
