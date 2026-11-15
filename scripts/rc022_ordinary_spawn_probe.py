"""Actual ordinary-process DTO/stdio consumer over native Windows launch."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from dsh.cordis import Context
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    from dsh.subprocess.error import subprocess_spawn_failure
    node=Path(sys.argv[sys.argv.index('--node')+1]);ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime);runtime=ctx.subprocess;rows=[]
    cases=[('collect',"process.stdout.write('hello你好');process.stderr.write('warn');process.exitCode=5",'ignore',dict(maxBytes=100)),('tail',"process.stdout.write('x'.repeat(1000)+'END')",'ignore',dict(maxBytes=64)),('batch',"let n=0;process.stdin.on('data',b=>n+=b.length);process.stdin.on('end',()=>process.stdout.write(String(n)))",dict(data='汉'*100000),dict(maxBytes=100)),('pipe',"process.stdin.pipe(process.stdout)",'pipe','pipe'),('missing','', 'ignore',dict(maxBytes=100))]
    try:
        for name,code,stdin,stdout in cases:
            program=str(WORKSPACE/'missing-program.exe') if name=='missing' else str(node)
            handle=runtime.spawn(dict(argv=[program,'-e',code],cwd=str(WORKSPACE),stdio=dict(stdin=stdin,stdout=stdout,stderr=dict(maxBytes=100)),graceMs=100))
            if name=='pipe':
                handle.stdin.write(b'raw input');handle.stdin.flush();handle.stdin.close()
                piped=await asyncio.get_running_loop().run_in_executor(None,handle.stdout.read)
                handle.stdout.close()
            else:piped=None
            try:result=dict(value=await handle.done)
            except Exception as error:result=dict(errorCode=subprocess_spawn_failure(error,program).code)
            await handle.waitForExit()
            rows.append(dict(name=name,result=result,stdout=handle.collected['stdout'].readFrom(0) if 'stdout' in handle.collected else None,stderr=handle.collected['stderr'].readFrom(0),piped=None if piped is None else piped.decode('utf-8'),stdin=handle.stdin is not None,stdoutPipe=handle.stdout is not None))
        return rows
    finally:await owner.dispose();await ctx.fiber.dispose();assert not runtime.live and not runtime.ordinary_cleanups


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_ordinary_spawn.mts','Actual Windows ordinary subprocess API: object spec, collected output DTOs, bounded tail offsets, UTF8, exit code, large batch stdin without blocking output, raw pipes and failed spawn retained empty collectors. Source may choose its documented fallback depending on native runner availability; native Job containment separately tested.',[Path(__file__).resolve(),ROOT/'dsh/subprocess/ordinary_authorized.py',ROOT/'dsh/subprocess/windows_process.py',ROOT/'dsh/subprocess/local.py'],prepare=prepare)
