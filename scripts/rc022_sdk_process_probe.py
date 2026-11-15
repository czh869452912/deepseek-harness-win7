"""Drive Source and native SDK runs over real child stdio pipes."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
SOURCE=None
NODE=None


def cases():
    return [dict(FAKE_REASON_KIND=kind) for kind in ('completed','max-tokens','blocked','error','interrupted','future','none')] + [dict(FAKE_REASON_KIND='aborted',FAKE_ABORT_REASON_KIND=kind) for kind in ('user','disposed')] + [dict(FAKE_EMPTY_MESSAGE='1',FAKE_REASON_KIND='max-tokens')] + [{key:value} for key,value in [('FAKE_MALFORMED','1'),('FAKE_INIT_ERROR','1'),('FAKE_MALFORMED_PROMPT','1'),('FAKE_MALFORMED_EVENT','1'),('FAKE_MALFORMED_MESSAGE','1'),('FAKE_MALFORMED_REASON','aborted'),('FAKE_EXIT_DURING_PROMPT','1'),('FAKE_STREAM_THEN_MALFORMED','1')]] + [dict(FAKE_ECHO_CWD='1',FAKE_ECHO_ENV='RC022_SDK_TOKEN,DSH_RC022_SDK_FACT')]


async def observe():
    from dsh.subagent import sdk_run as run
    from dsh.sdk.client import create_process_deepseek_harness
    from dsh.core.abort import AbortController
    original=run.internals.createHarness;rows=[]
    old={key:os.environ.get(key) for key in ('RC022_SDK_TOKEN','DSH_RC022_SDK_FACT')}
    os.environ.update(RC022_SDK_TOKEN='ambient',DSH_RC022_SDK_FACT='ambient')
    try:
        for index,env in enumerate(cases()):
            clients=[];reports=[]
            def create(options):
                runtime=dict(command=str(NODE),args=[str(SOURCE/'packages/sdk/client/tests/fake-runtime.ts')],cwd=options['processCwd'],
                    environment=lambda:options['env'],description='scripted SDK subagent runtime',initializeTimeoutMs=2000,
                    requestTimeoutMs=2000,shutdownTimeoutMs=100,disposeEofGraceMs=100,disposeGraceMs=500)
                harness=create_process_deepseek_harness(runtime,options);clients.append(harness.client);return harness
            run.internals.createHarness=create
            spec=dict(profile='sdk',patches=[],dshHome=str(WORKSPACE/'home'),cwd=str(WORKSPACE/'child'),originCwd=str(WORKSPACE/'origin'),
                provider='script',model='model',reasoningEffort='low',maxTokens=17,env=dict(env,FAKE_TEXT='answer',RC022_SDK_TOKEN='explicit'),
                shutdownTimeoutMs=100,disposeEofGraceMs=100,disposeGraceMs=500,onError=lambda error,reason:reports.append([type(error).__name__,reason]))
            try:
                handle=await run.start_sdk_run(dict(signal=AbortController().signal,prompt=[dict(type='text',text='task')]),spec)
                value=dict(result=await handle.result)
                first=handle.dispose();value['sameDisposal']=first is handle.dispose();await first
            except Exception as error:value=dict(startFailure=dict(name=getattr(error,'name',type(error).__name__),message=str(error)))
            value=json.loads(json.dumps(value).replace(str(WORKSPACE).replace('\\','\\\\'),'$WORKSPACE'))
            rows.append(dict(value=value,reports=reports,reaped=all(client.child is None or client.child.poll() is not None for client in clients),
                pipesClosed=all(client.child is None or all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr)) for client in clients),
                pending=sum(len(client.transport.pending) if client.transport is not None else 0 for client in clients)))
        return rows
    finally:
        run.internals.createHarness=original
        for key,value in old.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def prepare(output):
    global WORKSPACE,SOURCE,NODE
    WORKSPACE=output/'files'
    for folder in ('child','origin','home'):(WORKSPACE/folder).mkdir(parents=True)
    SOURCE=Path(sys.argv[sys.argv.index('--source')+1]).resolve();NODE=Path(sys.argv[sys.argv.index('--node')+1]).resolve()
    workspace_file=output/'workspace.json';workspace_file.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8')
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [workspace_file,path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_process.mts','Actual fixed Source scripted runtime subprocess driven by native/Source SDK run and client: real stdio handshake, working directory, prompt/wait, output and reason folding, protocol/transport errors, scrubbed environment, bounded shutdown and confirmed process exit. Does not qualify canonical SDK profile or provider assembly.',
        [Path(__file__).resolve(),ROOT/'dsh/sdk/client.py',ROOT/'dsh/subagent/sdk_run.py'],prepare=prepare)
