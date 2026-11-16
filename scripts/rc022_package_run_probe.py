"""Captured package run process boundary, compared with actual Source operations."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,os,sys,time
mode=sys.argv[1]
if mode=='success':print('installed')
elif mode=='empty':pass
elif mode=='failure':
    sys.stderr.write('EACCES denied\\n');sys.exit(7)
elif mode=='silent-failure':sys.exit(2)
elif mode=='large':sys.stdout.buffer.write(b'0123456789'*10000)
elif mode=='unicode':sys.stdout.buffer.write(('abc'+chr(0x4e2d)).encode('utf-8')*1000)
elif mode=='both':
    print('stdout',flush=True);time.sleep(.15);sys.stderr.write('stderr\\n');sys.stderr.flush()
elif mode=='progress':
    for _ in range(6):print('working',flush=True);time.sleep(.2)
elif mode in ('idle','cancel'):
    print('started',flush=True);time.sleep(10)
'''


def corpus():return ['success','empty','failure','silent-failure','large','unicode','both','progress','idle','cancel','pre-cancel','missing']


async def observe(workspace=None):
    from dsh.boot.plugin_package_run import run_package_process
    from dsh.core.abort import AbortController
    rows=[]
    for mode in corpus():
        directory=(workspace or WORKSPACE)/'native'/mode;directory.mkdir(parents=True)
        script=directory/'package.py';script.write_text(PROGRAM,encoding='utf-8')
        control=AbortController();output=dict(stdout='',stderr='')
        def emitted(text,stream):output[stream]+=text
        options=dict(outputBytes=13 if mode in ('large','unicode') else 4096,signal=control.signal,onOutput=emitted)
        if mode in ('idle','progress'):options['idleTimeoutMs']=500
        timer=asyncio.get_running_loop().call_later(.4,control.abort) if mode=='cancel' else None
        if mode=='pre-cancel':control.abort()
        command=str(directory/'missing.exe') if mode=='missing' else str(Path(sys.executable).resolve())
        try:result=await run_package_process(str(directory),[command,str(script),mode,'probe'],options)
        finally:
            if timer:timer.cancel()
        log=Path(result.pop('logPath')).read_bytes().decode('utf-8',errors='replace')
        if mode=='unicode':output={key:bool(value) for key,value in output.items()}
        if mode in ('silent-failure','pre-cancel','missing'):
            result['output']=bool(result['output']);log=bool(log);output={key:bool(value) for key,value in output.items()}
            if mode=='pre-cancel':
                sys.stderr.write(json.dumps(dict(nativePreCancelledExitCode=result.pop('exitCode')))+'\n')
            if mode=='missing':result['exitCode']=result['exitCode']!=0
        rows.append(dict(mode=mode,result=result,log=log,output=output,recordRemoved=not (directory/'.plugin-manager/run.json').exists()))
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_package_run.mts','Captured service process boundary compared with actual runProfilePnpm using an admitted profile and a controlled executable. No installation or package reconciliation is claimed. Empty-failure/missing/cancellation OS diagnostics normalized to presence.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_package_run.py'],prepare=prepare)
