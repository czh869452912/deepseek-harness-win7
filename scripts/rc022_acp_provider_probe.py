"""Actual ACP wire/provider observations against the fixed target."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    rows=[dict(name=reason,env=dict(PROBE_STOP=reason,PROBE_THOUGHT='1')) for reason in ('end_turn','max_tokens','refusal','cancelled','max_turn_requests','future')]
    rows += [dict(name=policy+'-'+reason,policy=policy,env=dict(PROBE_PERMISSION='1',PROBE_IGNORE_PERMISSION='1',PROBE_STOP=reason,PROBE_TOOL_KIND='execute')) for policy in ('allow','reject') for reason in ('end_turn','refusal','max_turn_requests')]
    rows += [dict(name='no-allow',policy='allow',env=dict(PROBE_PERMISSION='1',PROBE_NO_ALLOW='1')),
        dict(name='unknown-kind',env=dict(PROBE_PERMISSION='1',PROBE_IGNORE_PERMISSION='1',PROBE_STOP='refusal',PROBE_TOOL_KIND='future')),
        dict(name='cwd',env=dict(PROBE_ECHO_CWD='1')),dict(name='crash-start',env=dict(PROBE_CRASH_INITIALIZE='1')),
        dict(name='crash-prompt',env=dict(PROBE_CRASH_AFTER_CHUNK='1')),dict(name='missing-id',env=dict(PROBE_MISSING_ID='1')),
        dict(name='cancel',cancel=True,env=dict(PROBE_HANG='1',PROBE_IGNORE_CANCEL='1',PROBE_IGNORE_EOF='1'))]
    return rows


async def wait_file(path):
    deadline=asyncio.get_running_loop().time()+5
    while not path.exists():
        if asyncio.get_running_loop().time()>deadline:raise RuntimeError('ACP peer readiness not observed')
        await asyncio.sleep(.01)


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.subagent.acp_candidate import CandidateAcpProvider
    workspace=workspace or WORKSPACE;workspace.mkdir(parents=True,exist_ok=True);rows=[]
    for case in cases():
        ctx=Context();await ctx.plugin(LocalSubprocessRuntime);children=[];errors=[];controller=AbortController()
        original=ctx.subprocess.spawn
        def spawn(spec):
            child=original(spec);children.append(child);return child
        ctx.subprocess.spawn=spawn
        record=workspace/('native-'+case['name']+'.jsonl');ready=workspace/('native-'+case['name']+'.ready')
        config=dict(providerName='acp',command=sys.executable,args=[str(ROOT/'scripts/oracles/subagent_acp_peer.py')],
            env=dict(case['env'],PROBE_RECORD=str(record),PROBE_READY=str(ready)),permission=case.get('policy','reject'),disposeEofGraceMs=60,disposeGraceMs=100)
        provider=CandidateAcpProvider(ctx,config);provider.report=lambda error,reason:errors.append(reason)
        value={};handle=None
        try:
            try:
                handle=await provider.start(dict(cwd=str(workspace),parent=NS(session=NS(header=dict(cwd='intentionally-not-child-cwd'))),signal=controller.signal,
                    prompt=[dict(type='image',source=dict(type='url',url='private')),dict(type='text',text='explicit child task')]))
                if case.get('cancel'):await wait_file(ready);controller.abort()
                value['result']=await handle.result
                first=handle.dispose();value['sameDisposal']=first is handle.dispose();await first
                value['localAgentAbsent']=handle.localAgent is None
                value['distinctId']=handle.id!='same-child-id'
            except Exception as error:value['error']=dict(name=getattr(error,'name',type(error).__name__),message=str(error))
            value['quiescent']=all([await child.wait_for_exit() for child in children])
            value['exitCodes']=[(await child.done).exitCode for child in children]
            packets=[json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()] if record.exists() else []
            value['requests']=[dict(method=packet['method'],params=packet.get('params',{})) for packet in packets if 'method' in packet and packet['method']!='session/cancel']
            value=json.loads(json.dumps(value).replace(str(workspace).replace('\\','\\\\'),'$WORKSPACE'))
            rows.append(dict(name=case['name'],value=value,errorCount=len(errors),listeners=len(controller.signal._listeners)))
        finally:
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    config=output/'inputs.json';config.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=sys.executable,peer=str(ROOT/'scripts/oracles/subagent_acp_peer.py'),cases=cases())),encoding='utf-8');return [config]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_acp_provider.mts','ACP actual child process: captured cwd, initialize/new-session/prompt requests, text-only input and output, stop/permission diagnostics, startup/prompt failures, local cancellation, exact shared disposal and managed-range quiescence. Native candidate provider is used; Source run uses its actual subprocess seam.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/acp_candidate.py',ROOT/'scripts/oracles/subagent_acp_peer.py'],prepare=prepare,node_args=['--expose-internals'])
