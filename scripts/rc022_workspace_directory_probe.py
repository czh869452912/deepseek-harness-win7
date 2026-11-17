"""First-use directory resolution and actual Workspace Remote durable identity."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
FILES=None
CASES=[dict(platform=platform,stdout=stdout) for platform,stdout in [('darwin','/Users/a/文档/\n'),('win32','D:\\Redirected Documents\r\n'),('linux','/home/a/My Documents\n'),('linux',''),('linux','\r\n'),('linux','/home/a\n'),('freebsd','')]]
CASES += [dict(platform='win32',directory=value) for value in ['relative','C:relative','\\rooted','C:\\Docs\\..\\文档\\','\\\\server\\share','\\\\server\\share\\Documents']]
CASES += [dict(platform='linux',directory=value) for value in ['/documents','//documents/./a/../','relative']]


async def observe(files=None):
    from dsh.api.workspace_directory_current import default_workspace_directory
    from dsh.api.workspace_current import CurrentWorkspaceController
    from dsh.workspace.registry_022 import Current022WorkspacePlugin
    from dsh.core.abort import AbortController
    from dsh.cordis import Context
    from dsh.storage.storage_json import JsonStorageBackend
    from dsh.storage.domain_impl import DomainFacility
    from dsh.typert.current import CurrentTypertRegistry
    files=Path(files or FILES);rows=[]
    for case in CASES:
        calls=[]
        async def run(command,args,signal,visibility):calls.append(dict(command=command,arguments=len(args),visibility=visibility));return dict(stdout=case.get('stdout',''),stderr='')
        try:answer=dict(value=await default_workspace_directory(case.get('directory'),AbortController().signal,dict(platform=case['platform'],home='/home/a',run=run)))
        except Exception as error:answer=dict(error=str(error))
        rows.append(dict(case=case,calls=calls,**answer))
    ctx=Context();backend=JsonStorageBackend(str(files/'native'));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda _:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    async def listed():return []
    ctx.provide('sessionPersistence',SimpleNamespace(list=listed));ctx.provide('sessions',SimpleNamespace(get=lambda _:None,list=lambda:[]));ctx.provide('remoteAccess',SimpleNamespace(allows=lambda _:True))
    await ctx.plugin(Current022WorkspacePlugin);await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(CurrentWorkspaceController,dict(documentsDirectory=str(files/'Documents')))
    try:
        controller=ctx.workspaceController;first=await controller.initializeDefault(AbortController().signal)
        aborted=AbortController();aborted.abort();second=await controller.initializeDefault(aborted.signal)
        row=first['workspace'];rows.append(dict(step='first-remote',title=row['title'],path=row['path'],exists=Path(row['path']).is_dir(),same=row['workspaceId']==second['workspace']['workspaceId'],sessions=len(ctx.sessions.list())))
        await controller.delete(dict(workspaceId=row['workspaceId']))
        from dsh.core.session.json import UNDEFINED
        rows.append(dict(step='deleted-default',absent=await controller.initializeDefault(aborted.signal) is UNDEFINED))
    finally:await ctx.fiber.dispose();await facility.close_all();await backend.close()
    return rows


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES),cases=CASES)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_directory.mts','Documents path/OS command selection, unavailable roots and redirected UNC; actual JSON Remote first use, no Session allocation, identity reuse with aborted caller and deletion marker.',[Path(__file__).resolve(),ROOT/'dsh/api/workspace_directory_current.py',ROOT/'dsh/api/workspace_current.py'],prepare=prepare)
