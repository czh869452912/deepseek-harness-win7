"""Workspace pin/archive queue, activity admission and actual durable reopen."""
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
    from dsh.workspace.spec_022 import state
    files=Path(files or FILES);directory=files/'native';rows=[];trace=[];changes=[];live={'live':SimpleNamespace(header=dict(id='live',createdAt=1))};stored=[dict(id='stored',createdAt=0)]
    async def listed():return [dict(header=header,revision='revision') for header in stored]
    async def boot():
        ctx=Context();backend=JsonStorageBackend(str(directory));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
        facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
        ctx.provide('sessionPersistence',SimpleNamespace(list=listed));ctx.provide('sessions',SimpleNamespace(get=live.get,list=lambda:list(live.values())))
        fiber=ctx.plugin(Current022WorkspacePlugin);await fiber
        ctx.on('domain/changed',lambda change:changes.append(json.loads(json.dumps(change.value))) if change.table=='' else None)
        def activity(request,next_fn):trace.append(['activity',request['sessionId']]);return [dict(kind='turn')] if request['sessionId']=='live' else next_fn()
        ctx.on('workspace/session-activity',activity)
        def stopped(request):trace.append(['stop',request['sessionId'],ctx.workspaceRegistry.archivedSessionIds,ctx.workspaceRegistry.pinnedSessionIds])
        ctx.on('workspace/session-stop',stopped)
        ctx.on('workspace/session-archived',lambda request:trace.append(['archived',request['sessionId']]))
        ctx.on('workspace/session-unarchiving',lambda request:trace.append(['unarchiving',request['sessionId']]))
        return ctx,backend,facility
    ctx,backend,facility=await boot()
    async def close():await ctx.fiber.dispose();await facility.close_all();await backend.close()
    try:
        async def step(name,work):
            before=len(changes);start=len(trace);error=None
            try:await work()
            except Exception as exc:error=dict(name=getattr(exc,'name','Error'),message=str(exc),**(dict(activity=exc.activity) if hasattr(exc,'activity') else {}))
            row=dict(step=name,pinned=ctx.workspaceRegistry.pinnedSessionIds,archived=ctx.workspaceRegistry.archivedSessionIds,changes=len(changes)-before,trace=trace[start:])
            if error:row['error']=error
            rows.append(row)
        registry=ctx.workspaceRegistry
        for name,work in [('pin-live',lambda:registry.pinSession('live')),('pin-stored',lambda:registry.pinSession('stored')),('repeat-pin',lambda:registry.pinSession('live')),
            ('unknown-pin',lambda:registry.pinSession('missing')),('active-archive',lambda:registry.archiveSession('live')),('stop-archive',lambda:registry.archiveSession('live',dict(stopActivity=True))),
            ('repeat-archive',lambda:registry.archiveSession('live',dict(stopActivity=True))),('archived-pin',lambda:registry.pinSession('live')),('unknown-archive',lambda:registry.archiveSession('missing')),
            ('unarchive',lambda:registry.unarchiveSession('live')),('repeat-unarchive',lambda:registry.unarchiveSession('gone')),('unpin-unknown',lambda:registry.unpinSession('gone')),
            ('pin-again',lambda:registry.pinSession('live')),('archive-stored',lambda:registry.archiveSession('stored'))]:await step(name,work)
        await close();ctx,backend,facility=await boot();registry=ctx.workspaceRegistry
        async def nothing():pass
        await step('cold-reopen',nothing)
        await step('unpin',lambda:registry.unpinSession('live'))
        await step('clear-archive',lambda:registry.unarchiveSession('stored'))
    finally:await close()
    for patch in [{},dict(pinnedSessionIds=['x']),dict(pinnedSessionIds=[7]),dict(archivedSessionIds=None),dict(defaultWorkspaceId='held'),dict(defaultWorkspaceId=None),dict(pendingMutation=dict(operation='create',workspaceId='w',extra=True)),dict(pendingMutation=None)]:
        value=dict(initialized=True,workspaceIds=[],**patch)
        try:answer=dict(value=state(value))
        except Exception:answer=dict(rejected=True)
        rows.append(dict(step='schema',input=value,**answer))
    return rows


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_pins.mts','Current Workspace durable fields, pin order/idempotency, archive activity admission and stop-after-commit, unarchive/unpin, unknown/archived errors and actual JSON cold reopen.',[Path(__file__).resolve(),ROOT/'dsh/workspace/registry_022.py',ROOT/'dsh/workspace/spec_022.py',ROOT/'dsh/workspace/workspace.py'],prepare=prepare)
