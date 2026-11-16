"""Application-owned package executable seam over real child processes."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,os,sys,time
mode=sys.argv[1]
if mode in ('slow','cancel'):
    print('started',flush=True)
    time.sleep(10)
elif mode=='lines':
    sys.stdout.buffer.write(b'one\\r\\n\\r\\n');sys.stdout.flush()
    sys.stderr.buffer.write(b'two\\n\\n');sys.stderr.flush()
elif mode=='failure':
    print('{"error":{"code":"E404","message":"absent"}}')
    sys.stderr.write('registry unavailable\\n')
    sys.exit(7)
else:
    print(json.dumps(dict(args=sys.argv[2:],cwd=os.getcwd(),environment={name:os.environ.get(name) for name in ['DSH_PRIVATE_VALUE','EXAMPLE_SESSION_TOKEN','EXPLICIT_SECRET','CUSTOM_DATA']})))
'''


def corpus():return ['normal','registry','environment','lines','failure','slow','cancel','pre-cancel','missing']


async def observe(workspace=None):
    from dsh.boot.plugin_package_view import view_profile_package
    from dsh.core.abort import AbortController
    home=(workspace or WORKSPACE)/'native';home.mkdir(parents=True)
    script=home/'package.py';script.write_text(PROGRAM,encoding='utf-8')
    names=['DSH_PRIVATE_VALUE','EXAMPLE_SESSION_TOKEN']
    previous={name:os.environ.get(name) for name in names}
    os.environ.update(DSH_PRIVATE_VALUE='must-not-inherit',EXAMPLE_SESSION_TOKEN='must-not-inherit')
    rows=[]
    try:
        for mode in corpus():
            control=AbortController()
            options=dict(command=str(Path(sys.executable).resolve()),args=[str(script),mode],fields=['name','version','dsh'],timeoutMs=150 if mode=='slow' else 5000,signal=control.signal)
            if mode=='registry':options['registry']='https://corp.example/'
            if mode=='environment':options['env']=dict(EXPLICIT_SECRET='explicit',CUSTOM_DATA='value',DSH_PRIVATE_VALUE='explicit')
            if mode=='missing':options['command']=str(home/'not-a-program.exe')
            if mode=='pre-cancel':control.abort(RuntimeError('closed'))
            timer=asyncio.get_running_loop().call_later(.15,control.abort) if mode=='cancel' else None
            try:result=await view_profile_package(str(home),'@scope/pkg@^1.0',options)
            finally:
                if timer is not None:timer.cancel()
            if 'cause' in result:result['cause']=dict(code=result['cause'].code)
            if mode=='missing':result=dict(launchFailed=result['exitCode'] not in (0,) and bool(result.get('cause') or result['stderr']))
            if mode in ('normal','registry','environment'):
                value=json.loads(result['stdout']);value['cwd']='<profile>';result['stdout']=value
            if mode in ('slow','cancel'):result['stdout']=bool(result['stdout'])
            rows.append(dict(name=mode,result=result))
        return rows
    finally:
        for name,value in previous.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_package_view.mts','Actual Source viewProfilePackage and Python process adapter invoke the same owned fixture executable. Compare arguments/registry/no-retry flag, profile cwd, scrubbed ambient environment with explicit overrides, exit/output/newline handling, timeout/caller/pre-spawn cancellation and missing executable causes. Normalize only owned cwd and progress-output presence. This executable seam is not package installation or the built-in Python registry backend.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_package_view.py'],prepare=prepare)
