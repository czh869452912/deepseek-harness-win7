"""Current local and sandboxed filesystem mutations over real owned files."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSession
    from dsh.core.abort import AbortController
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.sandbox.policy_current import CurrentSandboxPolicy
    from dsh.fs.sandbox_current import CurrentFsSandbox
    from dsh.fs.patch import parse_patch
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    base=WORKSPACE/'native';workspace=base/'workspace';extra=base/'extra';other=base/'other'
    for directory in (workspace,extra,other):directory.mkdir(parents=True)
    ctx=Context();await ctx.plugin(Projections);await ctx.plugin(CurrentSandboxPolicy,dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(extra)]));await ctx.plugin(CurrentFsSandbox,dict(cwd=str(workspace)));fs=ctx.fs;rows=[]
    def project(value):
        if isinstance(value,NS) or hasattr(value,'__dict__'):return project(vars(value))
        if isinstance(value,dict):return {key:True if key=='version' else project(item) for key,item in value.items()}
        if isinstance(value,list):return [project(item) for item in value]
        return value
    async def call(name,operation):
        try:
            value=await operation();rows.append(dict(name=name,value=project(value)));return value
        except Exception as error:rows.append(dict(name=name,error=dict(code=error.code,message=error.message)));return None
    def hunks(old,new):return parse_patch('*** Begin Patch\n*** Update File: a\n@@\n-'+old+'\n+'+new+'\n*** End Patch')[0]['hunks']
    async def target(path):return await fs.resolve(str(path))
    try:
        path=extra/'text';text=await target(path);await call('write-extra',lambda:fs.writeText(text,'one\r\ntwo\r\n'))
        await call('edit-extra',lambda:fs.editText(text,dict(oldString='one',newString='ONE')));version=(await fs.stat(text)).version
        await call('patch-extra',lambda:fs.patchText(text,hunks('two','TWO')));rows.append(dict(name='patch-bytes',value=path.read_bytes().decode('utf-8')))
        await call('stale-patch',lambda:fs.patchText(text,hunks('absent','new'),dict(version=version)))
        await call('mismatch',lambda:fs.patchText(text,hunks('absent','new')))
        await call('delete-extra',lambda:fs.deleteFile(text));rows.append(dict(name='deleted',exists=path.exists()))
        source_path=workspace/'source';source=await target(source_path);destination_path=extra/'destination';destination=await target(destination_path);await fs.writeText(source,'old\r\n')
        await call('move-patched-new',lambda:fs.moveFile(source,destination,dict(hunks=hunks('old','new'),expectedDestination=dict(kind='createIfAbsent'))));rows.append(dict(name='moved-bytes',source=source_path.exists(),destination=destination_path.read_bytes().decode('utf-8')))
        await fs.writeText(source,'next\n');await call('blind-move-refused',lambda:fs.moveFile(source,destination,dict(expectedDestination=dict(kind='createIfAbsent'))));await call('same-target',lambda:fs.moveFile(source,source,{}))
        outside=await target(other/'outside');await call('move-destination-denied',lambda:fs.moveFile(source,outside,{}));rows.append(dict(name='denied-move-effects',source=source_path.read_text(encoding='utf-8'),outside=(other/'outside').exists()))
        source_path.write_bytes(b'\0binary');await call('binary-patch',lambda:fs.patchText(source,hunks('old','new')));await call('binary-delete',lambda:fs.deleteFile(source))
        await fs.writeText(source,'partial\n')
        class Error(Exception):pass
        def refuse(_):
            error=Error('refused');error.code='EACCES';raise error
        fs.internals.removeFile=refuse;await call('partial-move',lambda:fs.moveFile(source,destination,{}));fs.internals.removeFile=None
        rows.append(dict(name='partial-effects',source=source_path.read_text(encoding='utf-8'),destination=destination_path.read_text(encoding='utf-8')))
        controller=AbortController();fs.internals.inspectBeforeMutation=lambda _:controller.abort()
        await call('abort-before-move',lambda:fs.moveFile(source,destination,{},controller.signal));fs.internals.inspectBeforeMutation=None
        controller=AbortController();fs.internals.inspectTemp=lambda _:controller.abort()
        await call('abort-after-checkpoint',lambda:fs.moveFile(source,destination,{},controller.signal));fs.internals.inspectTemp=None;rows.append(dict(name='checkpoint-effects',aborted=controller.signal.aborted,source=source_path.exists(),destination=destination_path.read_text(encoding='utf-8')))
        readonly=dict(mode='read-only',workspaceRoot=str(workspace))
        for verb,operation in [('write',lambda:fs.writeText(destination,'bad',sandbox_policy=readonly)),('edit',lambda:fs.editText(destination,dict(oldString='partial',newString='bad'),sandbox_policy=readonly)),('patch',lambda:fs.patchText(destination,hunks('partial','bad'),sandbox_policy=readonly)),('delete',lambda:fs.deleteFile(destination,sandbox_policy=readonly)),('move',lambda:fs.moveFile(destination,source,{},sandbox_policy=readonly))]:await call('readonly-'+verb,operation)
        session=CurrentSession.create('grant',header=dict(version=4,id='grant',createdAt=0,isSeeded=False,cwd=str(workspace)),format_version=4)
        remove=ctx.sandboxPolicy.registerWritableRoot(session,str(other));granted=ctx.sandboxPolicy.resolve(dict(session=session));await call('runtime-grant',lambda:fs.writeText(outside,'granted',sandbox_policy=granted));remove()
        await call('revoked-grant',lambda:fs.writeText(outside,'bad',sandbox_policy=ctx.sandboxPolicy.resolve(dict(session=session))))
        await call('held-snapshot',lambda:fs.writeText(outside,'held',sandbox_policy=granted));rows.append(dict(name='held-effect',value=(other/'outside').read_text(encoding='utf-8')))
        missing=dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(base/'missing')]);await call('invalid-extra-before-workspace-write',lambda:fs.writeText(source,'bad',sandbox_policy=missing))
        rows[-1]['error']['message']=rows[-1]['error']['message'].split('cannot read the directory: ')[0]+'cannot read the directory: <platform diagnostic>'
        import _winapi
        alias=workspace/'junction';_winapi.CreateJunction(str(other),str(alias))
        try:
            (other/'existing').write_text('keep',encoding='utf-8')
            alias_existing=await target(alias/'existing');alias_new=await target(alias/'new')
            await call('junction-existing-denied',lambda:fs.writeText(alias_existing,'bad'))
            await call('junction-new-denied',lambda:fs.writeText(alias_new,'bad'))
            transient=workspace/'transient';transient.mkdir();transient.rmdir();_winapi.CreateJunction(str(other),str(transient))
            try:
                replaced=dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(transient)])
                await call('replaced-extra-denied',lambda:fs.writeText(source,'bad',sandbox_policy=replaced))
            finally:transient.rmdir()
            rows.append(dict(name='junction-effects',existing=(other/'existing').read_text(encoding='utf-8'),new=(other/'new').exists()))
        finally:alias.rmdir()
        rows.append(dict(name='locks-released',value=not fs._locks and not fs._lock_users))
        def normalize(value):
            if isinstance(value,str):return value.replace(json.dumps(str(base))[1:-1],'<root>').replace(str(base),'<root>')
            if isinstance(value,list):return [normalize(item) for item in value]
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            return value
        return normalize(rows)
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_fs_mutations.mts','Actual filesystem, policy/projection and owned files: write/edit/patch/delete/move with extra roots; raw CRLF storage, guards, binary/mismatch errors, new destination publication, partial move after source removal failure, signal checkpoint, all five read-only fences, runtime grant/revoke/held snapshot and validation before workspace write. Opaque version values project to presence; missing-root OS diagnostic body normalized.',[Path(__file__).resolve(),ROOT/'dsh/fs/local_current.py',ROOT/'dsh/fs/sandbox_current.py',ROOT/'dsh/fs/fs_local.py'],prepare=prepare)
