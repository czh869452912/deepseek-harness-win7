"""Actual directory provider, fs, Agent and projection journeys."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    root=(workspace or WORKSPACE)/'native';root.mkdir(parents=True)
    (root/'child').mkdir();(root/'child'/'nested').mkdir()
    fixture=await setup(root/'journal',directory=root);ctx=fixture.ctx;rows=[]
    try:
        agent=(await ctx.agents.create(dict(sessionId='one',meta=dict(cwd=str(root))))).agent
        other=(await ctx.agents.create(dict(sessionId='two',meta=dict(cwd=str(root))))).agent
        service=ctx.workingDirectory
        async def result(name,callback):
            try:rows.append(dict(name=name,value=await callback()))
            except Exception as error:rows.append(dict(name=name,error=dict(code=error.code,message=error.message)))
        await result('initial',lambda:service.ensure(agent))
        await result('change',lambda:service.set(agent,'child'))
        rows.append(dict(name='independent',other=service.get(other.session),original=agent.session.header.cwd))
        first=asyncio.create_task(service.set(agent,'nested'));second=asyncio.create_task(service.set(agent,'..'))
        rows.append(dict(name='serialized',values=await asyncio.gather(first,second)))
        await result('empty',lambda:service.set(agent,''));await result('missing',lambda:service.set(agent,'missing'))
        (root/'child'/'nested').rmdir();(root/'child').rmdir()
        await result('recover',lambda:service.ensure(agent))
        assembly=await ctx.systemPrompt.assemble(dict(agent=agent,scope=agent,signal=fixture.signal))
        rows.append(dict(name='context',value=[entry for entry in assembly['contexts'] if entry['name']=='working-directory:current']))
        rows.append(dict(name='changes',values=[event['data']['cwd'] for event in agent.session.snapshotEvents() if event['type']=='working-directory/change'],notices=[message['content'][0]['text'] for message in agent.inbox.nextStep if message['source']['kind']=='working-directory']))
        def normalize(value):
            if isinstance(value,str):return value.replace(json.dumps(str(root))[1:-1],'<root>').replace(str(root),'<root>')
            if isinstance(value,list):return [normalize(item) for item in value]
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            return value
        return normalize(rows)
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_directory.mts','Actual Local FS and working-directory provider with actual v4 Session/Agent/Projection/SystemPrompt: relative changes, per-Session serialization, missing/empty refusal, restoration and required prompt context. Paths projected to root.',
        [Path(__file__).resolve(),ROOT/'dsh/session/working_directory.py',ROOT/'dsh/core/system_prompt/current.py',ROOT/'scripts/rc022_subagent_fixture.py',ROOT/'scripts/oracles/rc022_subagent_fixture.mts'],prepare=prepare)
