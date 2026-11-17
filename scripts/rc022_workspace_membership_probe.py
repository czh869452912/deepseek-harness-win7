"""Actual-medium Workspace candidate projection and fresh header-index changes."""
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
    directory=Path(files or FILES)/'native';directory.mkdir(parents=True)
    project=directory/'project';project.mkdir();elsewhere=directory/'elsewhere';elsewhere.mkdir()
    stored=[];rows=[];live={}
    def header(identity,path=None):return dict(id=identity,createdAt=0,**({} if path is None else dict(cwd=str(path))))
    async def boot(medium='medium'):
        ctx=Context();backend=JsonStorageBackend(str(directory/medium))
        ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
        facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
        async def listed():return [dict(header=value,revision='r') for value in stored]
        ctx.provide('sessionPersistence',SimpleNamespace(list=listed))
        ctx.provide('sessions',SimpleNamespace(get=live.get,list=lambda:list(live.values())))
        await ctx.plugin(Current022WorkspacePlugin)
        return SimpleNamespace(ctx=ctx,backend=backend,facility=facility,registry=ctx.workspaceRegistry)
    async def close(host):await host.ctx.fiber.dispose();await host.facility.close_all();await host.backend.close()
    host=await boot();entity=await host.registry.create(str(project));identity=entity.id
    def clean(value):
        if isinstance(value,str):return value.replace(str(directory),'ROOT').replace('\\','/')
        if isinstance(value,list):return [clean(item) for item in value]
        if isinstance(value,dict):return {key:clean(item) for key,item in value.items()}
        return value
    async def step(name,work=None):
        error=None
        if work is not None:
            try:await work()
            except Exception as exc:error=dict(message=str(exc))
        rows.append(clean(dict(step=name,ids=entity.sessionIds,stored=host.registry._table.get(identity)['sessionIds'],
            status=await entity.status(),**({} if error is None else dict(error=error)))))
    try:
        stored[:]=[header('first',project),header('second',project),header('unowned',project)]
        await step('attach-first',lambda:entity.attachSession('first'))
        await step('attach-second',lambda:entity.attachSession('second'))
        await close(host);project.rmdir();host=await boot();entity=host.registry.get(identity)
        await step('missing-reopen')
        await step('missing-title-write',lambda:entity.setTitle('Still owned'))
        await step('missing-manual-order',lambda:entity.insertSessionBefore('first','second'))
        await step('missing-new-attach',lambda:entity.attachSession('unowned'))
        await close(host);host=await boot();entity=host.registry.get(identity);await step('second-reopen')
        # A never-indexed pin requires a new persistence listing. The Source
        # deliberately appends indexed headers here rather than clearing caches.
        stored[:]=[header('first',elsewhere),header('second',project),header('trigger-one',elsewhere)]
        await step('fresh-header-moves-first',lambda:host.registry.pinSession('trigger-one'))
        stored[:]=[header('first',project),header('second',project),header('trigger-two',elsewhere)]
        await step('fresh-header-missing-again',lambda:host.registry.pinSession('trigger-two'))
        stored[:]=[header('first'),header('second',project),header('trigger-three',elsewhere)]
        await step('fresh-header-without-cwd',lambda:host.registry.pinSession('trigger-three'))
        await step('write-prunes-invalid',lambda:entity.setTitle('Validated'))
        await step('detach-missing',lambda:entity.detachSession('second'))
        project.mkdir();stored[:]=[header('second',project)]
        await step('restore-reattach',lambda:entity.attachSession('second'))
        await close(host);stored.clear();host=await boot();entity=host.registry.get(identity)
        await step('absent-header-cold-reopen')
        await step('write-prunes-absent',lambda:entity.setTitle('No history'))
        await close(host);project.rmdir();stored[:]=[header('unowned',project)]
        host=await boot('fresh-medium');rows.append(dict(step='missing-never-bootstraps',workspaces=len(host.registry.list())))
    finally:await close(host)
    return rows


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_membership.mts','Current Workspace actual JSON cold membership across missing/restored directories; fresh header append clears per-id exemptions, absent cold headers prune on writes, and missing unowned paths never bootstrap.',
        [Path(__file__).resolve(),*[ROOT/'dsh/workspace'/name for name in ['registry_022.py','entity_022.py','entity.py','current.py','workspace.py']]],prepare=prepare)
