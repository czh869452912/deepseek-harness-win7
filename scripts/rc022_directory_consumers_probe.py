"""Pair file, search, shell and delivery consumers of the actual directory owner."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.core.tools import ToolExecutionInput
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.fs.tools_authorized import AuthorizedToolFs, AuthorizedToolFsSearch
    from dsh.fs.tool_present_authorized import AuthorizedToolPresent
    from dsh.context.file_reference_local.authorized import AuthorizedFileReferenceService
    from dsh.session.tool_working_directory import ToolWorkingDirectory
    from dsh.shell.tool_pwsh_authorized import AuthorizedToolPwsh
    base=workspace or WORKSPACE;directory=base/'native-work';directory.mkdir();moved=directory/'moved';moved.mkdir()
    (directory/'initial.txt').write_text('initial',encoding='utf-8');(moved/'current.txt').write_text('before\n',encoding='utf-8')
    fixture=await setup(base/'native',directory=directory);ctx=fixture.ctx;rows=[];requests=[];counter=[0]
    async def shell(request):
        requests.append(request)
        return dict(exitCode=0,signal=None,durationMs=1,timedOut=False,aborted=False,timeoutMs=1000,
                    stdout=dict(text='ok',truncated=False),stderr=dict(text='',truncated=False))
    ctx.set_service('shell',NS(sandboxMode=None,resolve=lambda request:request,run=shell));ctx.set_service('shellEnv',NS(collect=lambda _:{}))
    try:
        for plugin,config in [(LocalSubprocessRuntime,None),(AuthorizedToolFs,None),(AuthorizedToolFsSearch,dict(sampleOverCapGlobResults=False)),
                (ToolWorkingDirectory,None),(AuthorizedFileReferenceService,None),(AuthorizedToolPresent,None),(AuthorizedToolPwsh,dict(enableRunInBackground=False))]:await ctx.plugin(plugin,config)
        handle=await ctx.agents.create(dict(sessionId='consumer',meta=dict(cwd=str(directory)),agentOptions=dict(provider='script',model='model')));agent=handle.agent
        async def call(name,args,owner=agent):
            counter[0]+=1;result=await ctx.tools.execute(ToolExecutionInput('call-'+str(counter[0]),name,args,agent=owner,signal=fixture.signal))
            return dict(isError=result.isError,**(dict(code=result.error.get('code'),content=result.content) if result.isError else dict(value=result.value)))
        rows.append(dict(name='initial-directory',result=await call('working_directory',{})))
        rows.append(dict(name='initial-completion',value=await ctx.fileReferences.list(agent,'initial',fixture.signal)))
        old_search=ctx.fileReferences.searches[agent]
        rows.append(dict(name='changed-directory',result=await call('working_directory',dict(cd='moved'))))
        rows.append(dict(name='moved-completion',value=await ctx.fileReferences.list(agent,'current',fixture.signal),oldRetired=old_search._disposed))
        for label,name,args in [('read','read',dict(file_path='current.txt')),('write','write',dict(file_path='created.txt',content='created')),
                ('edit','edit',dict(file_path='current.txt',old_string='before',new_string='after')),('glob','glob',dict(pattern='*.txt')),
                ('grep','grep',dict(pattern='after',path='current.txt')),('shell','pwsh',dict(command='pwd',description='Show cwd')),
                ('relative-shell','pwsh',dict(command='pwd',description='Show cwd',workdir='..'))]:
            rows.append(dict(name=label,result=await call(name,args)))
        agent.session.append('turn/start',dict(turn=1))
        rows.append(dict(name='present',result=await call('present',dict(files=[dict(path='created.txt',description='Output')]))))
        rows.append(dict(name='delivery-record',files=[event['data']['files'] for event in agent.session.snapshotEvents() if event['type']=='deliverables/presented']))
        rows.append(dict(name='shell-cwd',values=[request['workdir'] for request in requests]))
        rows.append(dict(name='errors',empty=await call('working_directory',dict(cd='')),noAgent=await call('working_directory',{},None)))
        rows.append(dict(name='original-header',cwd=agent.session.header.cwd,current=ctx.workingDirectory.get(agent.session),createdAtOriginal=(directory/'created.txt').exists(),changedFile=(moved/'current.txt').read_text(encoding='utf-8')))
        await handle.dispose();await ctx.fiber.dispose()
        rows.append(dict(name='provider-unload',searches=len(ctx.fileReferences.searches) if ctx.get('fileReferences') is not None else 0,subprocessGone=ctx.get('subprocess') is None))
        def normalize(value):
            if isinstance(value,str) and str(directory) in value:return value.replace(str(directory),'<work>').replace('\\','/')
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            if isinstance(value,(list,tuple)):return [normalize(item) for item in value]
            return value
        return normalize(json.loads(json.dumps(rows)))
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_directory_consumers.mts','Actual Session/Agent/local FS/WorkingDirectory and tool pipeline: working_directory changes, completion index replacement, read/write/edit, real ripgrep subprocess glob/grep, one-shot shell workdir and relative override, absolute deliverable commit, original-header preservation and teardown. Shell command execution is a controlled provider; file/search execution is real. Paths in output strings are projected to <work>.',
        [Path(__file__).resolve()]+[ROOT/path for path in (
            'dsh/core/tools.py','dsh/fs/tools_authorized.py','dsh/fs/tool_fs.py','dsh/fs/tool_fs_mutation.py',
            'dsh/fs/tool_read.py','dsh/fs/tool_read_image.py','dsh/fs/tool_fs_search/__init__.py',
            'dsh/fs/tool_fs_search/search_core.py','dsh/session/tool_working_directory.py',
            'dsh/context/file_reference_local/authorized.py','dsh/shell/tool_pwsh_authorized.py',
            'dsh/shell/canonical_tool_pwsh.py','dsh/fs/tool_present_authorized.py')],prepare=prepare)
