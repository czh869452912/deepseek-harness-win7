"""Actual current PowerShell tool/job integration over a controlled shell provider."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_job_registry_probe import normalize
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.shell.tool_current import CurrentToolPwsh,DEFINITIONS
    from dsh.jobs.current import CurrentLocalJobRegistry
    from dsh.core.tools import ToolExecutionInput
    from dsh.core.abort import NEVER_ABORTED,abort_reason_error
    fixture=await setup(WORKSPACE/'native',script=[]);ctx=fixture.ctx;rows=[dict(name='definitions',value=DEFINITIONS)];specs=[];processes={};events=[]
    class Shell:
        sandboxMode=None
        def resolve(self,request):return dict(dict(workdir='C:/default',timeoutMs=40,stdoutMaxBytes=100,onExpiry='kill'),**request)
        async def execute(self,spec):
            specs.append({key:value for key,value in spec.items() if key!='signal'})
            if spec['command']=='prepare':await spec['signal'].wait_aborted();raise abort_reason_error(spec['signal'])
            done=asyncio.get_running_loop().create_future();out=['head'];proc=NS(status='running',exitCode=None,signal=None,sandbox=None,done=done)
            def read(offset):data=''.join(out).encode('utf-8');return dict(text=data[offset:].decode('utf-8',errors='replace'),nextOffset=len(data),lossy=False)
            proc.observed=NS(stdout=NS(readFrom=read),stderr=NS(readFrom=lambda _:dict(text='',nextOffset=0,lossy=False)))
            def finish(code=0):
                proc.status='completed';proc.exitCode=code
                if not done.done():done.set_result(None)
            def kill():
                proc.status='killed';proc.exitCode=1
                if not done.done():done.set_result(None)
            async def result():
                await asyncio.shield(done)
                return dict(exitCode=proc.exitCode,signal=None,timedOut=spec['command']=='fallback',aborted=False,timeoutMs=spec['timeoutMs'],stdout=dict(text=''.join(out),truncated=False),stderr=dict(text='',truncated=False))
            proc.kill=kill;proc.result=result;processes[spec['command']]=(proc,out,finish)
            if spec['command'] in ('fast','fallback'):finish(3)
            return proc
    ctx.set_service('shell',Shell());ctx.set_service('shellEnv',NS(collect=lambda _:dict(DSH_FACT='fact')))
    tool_owner=await ctx.plugin(CurrentToolPwsh);lease=await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')));agent=lease.agent
    jobs_owner=None
    async def call(command,**args):
        arguments=dict(command=command,description='Run controlled command',**args);tool=ctx.tools.get('pwsh');result=await ctx.tools.execute(ToolExecutionInput('call','pwsh',arguments,agent=agent,signal=NEVER_ABORTED))
        return dict(isError=result.is_error,value=result.value,content=result.content,meta=result.meta,call=tool.present_call(arguments),presentation=tool.present_result(arguments,result))
    async def drain():
        for _ in range(12):await asyncio.sleep(0)
    try:
        rows.append(dict(name='foreground-only',value=await call('fast',workdir='sub')))
        jobs_owner=await ctx.plugin(CurrentLocalJobRegistry,dict(pumpPollMs=2));jobs=ctx.jobs;detach=jobs.attachController('test');jobs.events.subscribe(dict(owners='all'),lambda event:events.append(event))
        rows.append(dict(name='registered-fast',value=await call('fast'),jobs=jobs.list('root')))
        promoted=await call('long');identity=promoted['value']['jobId'];rows.append(dict(name='promoted',value=promoted,ui=jobs.readAt(identity,0,'root')))
        processes['long'][1].append('tail');processes['long'][2](0);await jobs.wait(identity,10000,'root');rows.append(dict(name='after-promotion',read=jobs.read(identity,'root')));jobs.remove(identity,'root')
        background=await call('background',run_in_background=True);identity=background['value']['jobId'];await drain()
        while jobs.get(identity,'root')['output']['total']<4:await asyncio.sleep(.001)
        rows.append(dict(name='background',value=background))
        jobs.kill(identity,'root','human stopped');await jobs.wait(identity,10000,'root');rows.append(dict(name='background-killed',read=jobs.read(identity,'root')));jobs.remove(identity,'root')
        rows.append(dict(name='prepare-timeout',value=await call('prepare'),jobs=jobs.list('root')))
        detach();rows.append(dict(name='admission-fallback',value=await call('fallback')))
        await jobs_owner.dispose();jobs_owner=None
        rows.append(dict(name='unloaded-registry',background='run_in_background' in ctx.tools.get('pwsh').parameters['properties']))
        rows.append(dict(name='specs',value=specs));rows.append(dict(name='events',value=events))
        return normalize(json.loads(json.dumps(rows)))
    finally:
        for proc,out,finish in processes.values():
            if not proc.done.done():proc.kill()
        if jobs_owner is not None:await jobs_owner.dispose()
        await lease.dispose();await tool_owner.dispose();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_pwsh_tool.mts','Actual current PowerShell tool, tool pipeline and job registry/Agent/Session. Paired six Source-derived metadata variants, dynamic registry registration, foreground completed cleanup, promotion consuming cursor/UI reads, explicit background and outside kill, preparation timeout, admission fallback, cwd/env/specs, ordered lifecycle and generic/terminal presentations. Shell executor is controlled; actual executor separately qualified.',[Path(__file__).resolve(),ROOT/'dsh/shell/tool_current.py',ROOT/'dsh/shell/pwsh_current.json',ROOT/'scripts/oracles/rc022_pwsh_definition.mts'],prepare=prepare)
