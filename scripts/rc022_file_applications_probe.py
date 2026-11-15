"""Pair file association adapters and verified controller desktop intents."""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.host.file_applications import native_file_applications,open_native_file_application,RESOURCES
    from dsh.host.native_command_current import open_native_associated_path
    workspace=workspace or WORKSPACE;rows=[];signal=AbortController().signal
    apps=[dict(id='app',name='Editor',default=True,icon=None)]
    for action in ('query','long-open','wsl','cancel','failure'):
        scripts=[];calls=[];controller=AbortController()
        async def run(command,args,signal):
            calls.append(command)
            if command=='wslpath':return dict(stdout='C:\\translated.txt\r\n',stderr='')
            script=Path(args[-1]);text=script.read_text(encoding='utf-8');encoded=re.findall(r"FromBase64String\('([^']*)'\)",text)
            scripts.append(script)
            decoded=[base64.b64decode(item).decode('utf-8') for item in encoded]
            rows.append(dict(name=action+'-invocation',command=command,bom=text.startswith('\ufeff'),path=decoded[0] if action!='long-open' else len(decoded[0]),application=decoded[1],fileArgument='-File' in args,smallArgv=sum(len(item) for item in args)<500,sourceHelper='public static class DshFileAssociations' in text))
            if action=='cancel':controller.abort(RuntimeError('cancelled'));signal.throwIfAborted()
            if action=='failure':raise RuntimeError('helper failed')
            return dict(stdout=json.dumps(apps),stderr='')
        options=dict(platform='linux' if action=='wsl' else 'win32',env=dict(WSL_INTEROP='yes') if action=='wsl' else {},osRelease='linux',run=run)
        try:
            if action=='long-open':await open_native_file_application('C:/'+('a'*35000)+"\u6d4b\u8bd5' &.txt",'app',controller.signal,options)
            else:rows.append(dict(name=action+'-result',value=await native_file_applications("C:/file' &.txt",controller.signal,options)))
        except Exception as error:rows.append(dict(name=action+'-error',message=str(error)))
        rows.append(dict(name=action+'-cleanup',gone=all(not path.exists() and not path.parent.exists() for path in scripts),calls=calls))
    mac=[dict(id='/Apps/old.app',name='Editor',default=False,icon=None,bundle='bundle',version='1.9'),dict(id='/Apps/new.app',name='Editor',default=False,icon=None,bundle='bundle',version='2.0'),dict(id='/Apps/preferred.app',name='Editor',default=True,icon=None,bundle='bundle',version='1.0'),dict(id='/Apps/side.app',name='Editor Beta',default=False,icon=None,bundle='bundle',version='9')]
    calls=[]
    async def mac_run(command,args,signal):
        calls.append([command]+([args[-1]] if command=='osascript' else args));return dict(stdout=json.dumps(mac),stderr='')
    options=dict(platform='darwin',env={},run=mac_run)
    rows.append(dict(name='mac-dedupe',value=await native_file_applications('/file.txt',signal,options)))
    await open_native_file_application('/file.txt','/Apps/old.app',signal,options)
    try:await open_native_file_application('/file.txt','/arbitrary.app',signal,options)
    except Exception as error:rows.append(dict(name='mac-stale',message=str(error)))
    rows.append(dict(name='mac-launch-calls',value=calls))
    calls=[]
    async def linux_run(command,args,signal):
        calls.append([command]+args)
        return dict(stdout='standard::content-type: text/plain' if command=='gio' and args[0]=='info' else 'Default application for text/plain: nested-editor.desktop\nRegistered applications:\n  nested-editor.desktop\n  hidden.desktop\n  missing.desktop\n',stderr='')
    options=dict(platform='linux',env=dict(HOME=str(workspace),XDG_DATA_HOME=str(workspace/'xdg'),XDG_DATA_DIRS='',LANG='zh_CN.UTF-8'),osRelease='linux',run=linux_run)
    applications=await native_file_applications('/file.txt',signal,options)
    rows.append(dict(name='linux-catalog',value=applications))
    await open_native_file_application('/file.txt',applications[0]['id'],signal,options)
    rows.append(dict(name='linux-launch-calls',value=calls))
    association_calls=[]
    async def associated(command,args,signal):association_calls.append([command]+args);return dict(stdout='',stderr='')
    await open_native_associated_path('/page.html',signal,dict(platform='linux',env=dict(BROWSER='browser'),osRelease='linux',run=associated))
    await open_native_associated_path('/page.html',signal,dict(platform='darwin',env={},run=associated))
    rows.append(dict(name='associated-html',value=association_calls))
    ctx=Context();trace=[]
    try:
        await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(FsLocalPlugin,dict(cwd=str(workspace)))
        async def opened(path,signal):trace.append(dict(kind='open',path=path))
        async def reveal(path,signal):trace.append(dict(kind='reveal',path=path))
        async def explicit(path,app,signal):trace.append(dict(kind='explicit',path=path,application=app))
        async def catalog(path,signal):trace.append(dict(kind='catalog',path=path));return apps
        api=AuthorizedSessionController(ctx,dict(nativeOpen=True),dict(openPath=opened,revealPath=reveal,openFileApplication=explicit,fileApplications=catalog))
        for request in (dict(path=str(workspace/'file.txt')),dict(path=str(workspace/'file.txt'),action='reveal',application='ignored'),dict(path=str(workspace/'file.txt'),application='app')):
            rows.append(dict(name='desktop-open',value=await api.openWorkspacePath(request,signal)))
        rows.append(dict(name='desktop-catalog',value=await api.workspacePathApplications(dict(path=str(workspace/'file.txt')),signal)))
        rows.append(dict(name='desktop-trace',value=trace))
        for kind in ('empty','unmapped','roundtrip','cancelled','native-error'):
            abort=AbortController();original_mapping=ctx.fs.processPathFromHostPath;original_process=ctx.fs.processPath;original_open=api.open_path
            if kind=='unmapped':ctx.fs.processPathFromHostPath=lambda _:None
            if kind=='roundtrip':ctx.fs.processPath=lambda _:'different'
            if kind=='cancelled':abort.abort()
            if kind=='native-error':
                async def fail(*_):raise RuntimeError('native failure')
                api.open_path=fail
            try:await api.openWorkspacePath(dict(path='' if kind=='empty' else str(workspace/'file.txt')),abort.signal)
            except Exception as error:rows.append(dict(name='desktop-'+kind,code=error.code,message=str(error),hasCause=error.cause is not None))
            finally:ctx.fs.processPathFromHostPath=original_mapping;ctx.fs.processPath=original_process;api.open_path=original_open
        api.can_open=lambda:False
        abort=AbortController();abort.abort();rows.append(dict(name='disabled-catalog',value=await api.workspacePathApplications(dict(path=''),abort.signal)))
    finally:await ctx.fiber.dispose()
    def normalize(value):
        if isinstance(value,str):return value.replace(str(workspace),'<workspace>').replace('\\','/')
        if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
        if isinstance(value,(list,tuple)):return [normalize(item) for item in value]
        return value
    return normalize(rows)


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    entries={'file.txt':'text','xdg/applications/nested/editor.desktop':'[Desktop Entry]\nName=Editor\nName[zh]=Chinese\nName[zh_CN]=Local Editor\nIcon=editor\nExec=NEVER EXECUTE\n[Desktop Action Other]\nName=Ignored\n','xdg/applications/hidden.desktop':'[Desktop Entry]\nName=Hidden\nHidden=true\n','xdg/icons/hicolor/32x32/apps/editor.png':'pixels'}
    inputs=[]
    for name,text in entries.items():
        path=WORKSPACE/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');inputs.append(path)
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]+inputs


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_file_applications.mts','File association providers with controlled native commands: encoded private Windows script, long paths, WSL, cancellation/failure cleanup, macOS display deduplication versus raw launch validation, Linux XDG locale/hidden/icon handling and GIO launch. Actual local FS and controller desktop mapping verify intent routing, round-trip refusal and errors; OS queries and launches are separately tested natively.',
        [Path(__file__).resolve(),ROOT/'dsh/host/file_applications.py',ROOT/'dsh/host/native_command_current.py',ROOT/'dsh/host/resources/file_associations.cs',ROOT/'dsh/host/resources/file_applications.jxa',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
