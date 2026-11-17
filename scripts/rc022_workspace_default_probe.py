"""First-use Workspace identity and journal rollback/recovery on actual JSON."""
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
    files=Path(files or FILES);rows=[]
    async def boot(directory):
        ctx=Context();backend=JsonStorageBackend(str(directory/'medium'));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
        facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
        async def listed():return []
        ctx.provide('sessionPersistence',SimpleNamespace(list=listed));ctx.provide('sessions',SimpleNamespace(get=lambda _:None,list=lambda:[]))
        await ctx.plugin(Current022WorkspacePlugin)
        return SimpleNamespace(ctx=ctx,backend=backend,facility=facility,registry=ctx.workspaceRegistry)
    async def close(host):await host.ctx.fiber.dispose();await host.facility.close_all();await host.backend.close()
    def snapshot(host):
        registry=host.registry;state=registry._global.get()
        return dict(order=len(state['workspaceIds']),records=registry._table.size,cache=len(registry.list()),default='defaultWorkspaceId'in state,pending=state.get('pendingMutation',{}).get('operation'))
    directory=files/'native-default';directory.mkdir(parents=True);host=await boot(directory);lookups=[]
    async def resolve():lookups.append(True);return str(directory/'nested/Workspace')
    try:
        first,last=await asyncio.gather(host.registry.initializeDefault(resolve),host.registry.initializeDefault(resolve))
        rows.append(dict(step='concurrent',same=first is last,title=first.title,exists=Path(first.path).is_dir(),lookups=len(lookups),state=snapshot(host)))
        await first.setTitle('Renamed');await close(host);host=await boot(directory)
        found=await host.registry.initializeDefault(resolve)
        rows.append(dict(step='reopened',title=found.title,lookups=len(lookups),state=snapshot(host)))
        await host.registry.delete(found.id);await close(host);host=await boot(directory)
        found=await host.registry.initializeDefault(resolve)
        rows.append(dict(step='deleted',absent=found is None,lookups=len(lookups),state=snapshot(host)))
    finally:await close(host)
    for mode in ['record','record-rollback','order','order-delete-rollback','order-state-rollback','delete-cleanup','delete-state-rollback']:
        directory=files/('native-'+mode);directory.mkdir();host=await boot(directory);registry=host.registry;path=directory/'project';path.mkdir()
        if mode.startswith('delete'):entity=await registry.create(str(path))
        original_state=registry._set_state;original_put=registry._table.put;original_delete=registry._table.delete;state_calls=[]
        async def set_state(value):
            state_calls.append(value)
            failing=([2] if mode in ['order','order-delete-rollback','delete-cleanup'] else [2,3] if mode=='order-state-rollback' else [2] if mode in ['record-rollback','delete-state-rollback'] else [])
            if len(state_calls) in failing:raise RuntimeError('selected state write')
            await original_state(value)
        async def put(*args):
            if mode.startswith('record'):raise RuntimeError('selected record write')
            return await original_put(*args)
        async def delete(*args):
            if mode in ['order-delete-rollback','delete-state-rollback']:raise RuntimeError('selected record delete')
            return await original_delete(*args)
        registry._set_state=set_state;registry._table.put=put;registry._table.delete=delete
        try:
            try:
                result=await registry.delete(entity.id) if mode.startswith('delete') else await registry.create(str(path));error=None
            except Exception as exc:error=dict(name=getattr(exc,'name','Error'),causes=[str(item) for item in getattr(exc,'errors',[])])
            rows.append(dict(step=mode,error=error,state=snapshot(host)))
            registry._set_state=original_state;registry._table.put=original_put;registry._table.delete=original_delete
            await close(host);host=await boot(directory);rows.append(dict(step=mode+'-reopened',state=snapshot(host)))
        finally:await close(host)
    return rows


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_default.mts','Actual JSON first-use identity across concurrent calls/reopen/delete plus record/order/journal rollback failures and recoverable marker cold recovery.',[Path(__file__).resolve(),ROOT/'dsh/workspace/registry_022.py',ROOT/'dsh/workspace/spec_022.py'],prepare=prepare)
