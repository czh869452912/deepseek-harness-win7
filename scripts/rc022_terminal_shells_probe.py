"""Target shell profiles and actual local executable lookup."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.api.terminal_shells_authorized import resolve_shell,discover_shells,find_shell
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime,SubprocessExecutableNotFoundError
    rows=[];signal=AbortController().signal
    for platform,path in [('windows',None),('posix',None),('windows','C:\\Tools\\PowerShell.EXE'),('posix','/bin/zsh')]:
        calls=[]
        async def environment(signal):calls.append('environment');return dict(platform=platform,**(dict(defaultShell=path) if path is not None else {}))
        async def resolve(command,env,signal):calls.append(command);return command
        provider=NS(terminalEnvironment=environment,resolveExecutable=resolve)
        rows.append(dict(name='default-'+platform+'-'+str(len(rows)),value=await resolve_shell(provider,None,signal),calls=calls))
    calls=[]
    async def resolve(command,env,signal):
        calls.append(command)
        if command=='missing':raise SubprocessExecutableNotFoundError('not installed')
        if command=='offline':raise RuntimeError('transport offline')
        return command
    provider=NS(terminalEnvironment=environment,resolveExecutable=resolve)
    configured=dict(path='/bin/bash',args=['--noprofile','-i'],name='Configured')
    shells=await discover_shells(provider,configured,['/usr/bin/BASH','powershell.exe','C:\\tools\\PWSH.EXE','missing','cmd'],signal)
    rows.append(dict(name='discovered',value=shells,calls=list(calls)))
    for name in ('Bash.exe','C:\\bin\\PwSh','powershell','missing'):
        rows.append(dict(name='find-'+name,value=find_shell(shells,name)))
    try:await discover_shells(provider,configured,['offline'],signal)
    except RuntimeError as error:rows.append(dict(name='transport-failure',message=str(error)))
    base=(workspace or WORKSPACE)/'native';first=base/'first';second=base/'second';first.mkdir(parents=True);second.mkdir()
    (first/'dsh-shell.exe').write_bytes(b'');(second/'dsh-shell.exe').write_bytes(b'');(first/'directory.exe').mkdir()
    ctx=Context();runtime=AuthorizedLocalSubprocessRuntime(ctx)
    try:
        env=dict(PATH=str(first)+';'+str(second),PATHEXT='.EXE;.CMD')
        rows.append(dict(name='local-path',value=await runtime.resolveExecutable('dsh-shell',env,signal)))
        rows.append(dict(name='local-absolute',value=await runtime.resolveExecutable(str(second/'dsh-shell.exe'),None,signal)))
        for name in ('absent','directory',str(first/'missing.exe'),'./relative',''):
            try:await runtime.resolveExecutable(name,env,signal)
            except Exception as error:rows.append(dict(name='lookup-'+name.replace(str(first),'<first>'),message=str(error),code=getattr(error,'code',None),typed=getattr(error,'name',None)=='SubprocessExecutableNotFoundError'))
        controller=AbortController();failure=RuntimeError('cancel lookup');controller.abort(failure)
        try:await runtime.resolveExecutable('dsh-shell',env,controller.signal)
        except RuntimeError as error:rows.append(dict(name='lookup-cancellation',same=error is failure))
        result=await runtime.terminalEnvironment(signal)
        rows.append(dict(name='local-environment',platform=result['platform'],hasDefault=isinstance(result.get('defaultShell'),str)))
        def normalize(value):
            if isinstance(value,str):return value.replace(str(base),'<work>').replace(json.dumps(str(base))[1:-1],'<work>')
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            if isinstance(value,list):return [normalize(item) for item in value]
            return value
        return normalize(rows)
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_shells.mts','Target-environment default/configured shell profiles, ordered parallel candidate discovery, kind deduplication, typed lookup miss versus transport failure, case-insensitive name selection. Actual local PATH/PATHEXT order, absolute executable lookup, directories and missing/relative/empty paths and cancellation identity. Owned roots normalize to <work>; environment default shell reduced to presence, not cross-process path equivalence.',
        [Path(__file__).resolve(),ROOT/'dsh/api/terminal_shells_authorized.py',ROOT/'dsh/subprocess/local_authorized.py'],prepare=prepare)
