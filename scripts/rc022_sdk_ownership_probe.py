"""SDK handshake and child teardown remain owned after an observer leaves."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=SOURCE=NODE=None


async def scenario(kind):
    from dsh.sdk.client import create_process_deepseek_harness
    directory=WORKSPACE/'native'/kind;directory.mkdir(parents=True)
    ready,go,record=(directory/name for name in ('ready','go','record'))
    env=dict(os.environ,FAKE_RECORD_INIT=str(record))
    startup=kind.startswith('start')
    if startup:env.update(FAKE_INIT_READY=str(ready),FAKE_INIT_GO=str(go))
    else:env['FAKE_IGNORE_EOF']='1'
    if kind=='start-failure':env['FAKE_INIT_ERROR_ONCE_FILE']=str(directory/'failed')
    runtime=dict(command=str(NODE),args=[str(SOURCE/'packages/sdk/client/tests/fake-runtime.ts')],
        cwd=str(directory),environment=lambda:env,description='SDK owner fixture',initializeTimeoutMs=3000,
        requestTimeoutMs=3000,shutdownTimeoutMs=100,disposeEofGraceMs=100,disposeGraceMs=500)
    harness=create_process_deepseek_harness(runtime,dict(cwd=str(directory),provider='script',model='model'))
    original=harness.client;clients=[original]
    try:
        if startup:
            shared=harness.start();same=shared is harness.start()
            async def wait_ready():
                while not ready.exists():await asyncio.sleep(.005)
            await asyncio.wait_for(wait_ready(),5)
        else:
            await harness.start();shared=harness.close();same=shared is harness.close()
        async def wait():return await shared
        one,two=asyncio.create_task(wait()),asyncio.create_task(wait())
        await asyncio.sleep(0)
        if kind.endswith('timeout'):
            try:await asyncio.wait_for(one,.01)
            except asyncio.TimeoutError:pass
        else:
            one.cancel()
            try:await one
            except asyncio.CancelledError:pass
        pending=not shared.done() and not two.done()
        live=original.child.poll() is None
        go.write_text('release',encoding='utf-8')
        failure=None
        try:await asyncio.wait_for(two,5)
        except Exception as error:failure=type(error).__name__
        swapped=harness.client is not original
        if swapped:
            clients.append(harness.client);await harness.start()
        handshake_count=len(record.read_text(encoding='utf-8').splitlines())
        await harness.close()
        return dict(kind=kind,sameHandle=same,pending=pending,liveAtAbandonment=live,
            failure=failure,swapped=swapped,handshakes=handshake_count,
            reaped=all(client.child.poll() is not None for client in clients),
            pipesClosed=all(all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr)) for client in clients),
            pendingRequests=sum(len(client.transport.pending) for client in clients))
    finally:
        go.write_text('release',encoding='utf-8');await harness.close()


async def observe():
    return [await scenario(kind) for kind in ('start-abandon','start-timeout','start-failure','close-abandon','close-timeout')]


def prepare(output):
    global WORKSPACE,SOURCE,NODE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    SOURCE=Path(sys.argv[sys.argv.index('--source')+1]).resolve()
    NODE=Path(sys.argv[sys.argv.index('--node')+1]).resolve()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8')
    inputs=output/'sdk-source-inputs.json'
    inputs.write_text(json.dumps({name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in
        ('packages/sdk/client/src/client.ts','packages/sdk/client/src/api.ts','packages/sdk/client/src/dispose.ts','packages/sdk/client/tests/fake-runtime.ts')},indent=2),encoding='utf-8')
    return [path,inputs]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_ownership.mts',scope='Actual original scripted Node runtime through both SDKs: independent handshake/close observers, timeout, original initialization rejection followed by owned cleanup and retry, EOF/termination ladder and closed pipes. Python cancellation corresponds to JS Promise.race observer abandonment.',
        prepare=prepare,extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/sdk/client.py',ROOT/'dsh/core/cleanup.py'])
