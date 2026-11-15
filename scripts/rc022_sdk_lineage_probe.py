"""SDK lineage DTOs from real nested activations, after local disposal."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.sdk.server import HarnessSdkJsonRpcServer
    fixture=await setup(WORKSPACE/'native');ctx=fixture.ctx;service=fixture.service;notes=[];rows=[]
    server=HarnessSdkJsonRpcServer(ctx,NS(notify=lambda method,params:notes.append(dict(method=method,params=params))))
    async def start(parent,identity):
        receipt=await service.startActivation(dict(provider='spawn',parent=parent,childId=identity,name=identity,label='Task',prompt=[dict(type='text',text='task')],signal=fixture.signal,delivery='caller'))
        while ctx.agents.get(identity).status!='running':await asyncio.sleep(.001)
        return receipt,ctx.agents.get(identity)
    try:
        await server.initialize(dict(cwd=str(WORKSPACE),provider='script',model='model'))
        parent=(await server.get_or_create('root')).agent
        outer,child=await start(parent,'child');inner,grandchild=await start(child,'grandchild')
        await inner['dispose']();await inner['result'];await outer['dispose']();await outer['result'];await asyncio.sleep(0)
        rows.append(dict(name='actual-nested',notifications=[note for note in notes if note['method'].startswith('subagent.')],live=[ctx.agents.get(identity) is not None for identity in ['root','child','grandchild']]))
        notes.clear()
        for origin in ['user','fork','subagent']:
            server.session_created(NS(id=origin,header=NS(origin=origin,parentSession='creator')))
        rows.append(dict(name='origin-filter',notifications=list(notes)));notes.clear()
        output=[dict(type='text',text='retained')]
        server.subagent_end(dict(local=False,provider='remote',id='same-id',parentSessionId='unrelated',stopReason='completed'))
        server.subagent_end(dict(local=True,provider='removed-provider',id='retired',parentSessionId='direct-parent',stopReason='max-tokens',lastAssistantMessage=output))
        output.append(dict(type='text',text='later mutation'))
        rows.append(dict(name='payload-owned',notifications=list(notes)))
        # SDK notifications cross JSON-RPC; immutable Session block wrappers
        # have the same wire representation as ordinary dicts/lists.
        return json.loads(json.dumps(rows))
    finally:await server.shutdown();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_lineage.mts','Actual SDK observers and local nested Subagent activations. Direct creator id persists through child disposal independent of scoped tree-root dispatch. Also origin filtering, external locality exclusion, removed-provider snapshot and copied output list.',[Path(__file__).resolve(),ROOT/'dsh/sdk/server.py',ROOT/'dsh/subagent/lifecycle_current.py',ROOT/'dsh/subagent/lifetime.py'],prepare=prepare)
