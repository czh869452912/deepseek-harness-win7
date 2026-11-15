"""SDK cold resume, owned idle wait and failure retirement on real v4 services."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.sdk.server import HarnessSdkJsonRpcServer
    fixture=await setup(WORKSPACE/'native',script=[],directory=WORKSPACE);ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None));rows=[]
    async def call(method,params):
        try:return dict(value=await server.handle_request('session/'+method,params))
        except Exception as error:return dict(error=getattr(error,'message',str(error)),name=getattr(error,'name','TypeError' if isinstance(error,TypeError) else 'Error'))
    def record(name,result):rows.append(dict(name=name,result=result))
    try:
        for method in ('resume','wait'):record('before-'+method,await call(method,dict(sessionId='a')))
        await server.initialize(dict(cwd=str(WORKSPACE),provider='script',model='model'))
        for name,method,params in [('resume-id','resume',{}),('resume-empty','resume',dict(sessionId='')),('wait-id','wait',{}),('wait-empty','wait',dict(sessionId='')),('wait-unknown','wait',dict(sessionId='unknown')),('resume-missing','resume',dict(sessionId='missing'))]:record(name,await call(method,params))
        handle=await ctx.agents.create(dict(sessionId='persisted',meta=dict(cwd=str(WORKSPACE)),agentOptions=dict(provider='script',model='model')))
        await ctx.workingDirectory.set(handle.agent,str(WORKSPACE/'child'))
        handle.agent.session.append('turn/start',dict(turn=1));handle.agent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        await handle.dispose()
        record('resume',await call('resume',dict(sessionId='persisted',ignored=True)))
        agent=server.sessions['persisted'].agent
        rows.append(dict(name='restored',id=agent.id,cwd=await ctx.workingDirectory.ensure(agent),origin=agent.session.header.cwd,model=agent.model.current()))
        record('resume-owned',await call('resume',dict(sessionId='persisted')))
        record('wait-owned',await call('wait',dict(sessionId='persisted')))
        error=RuntimeError('active failure');ctx.emit('agent/error',dict(agent=agent,error=error));record('failure',await call('wait',dict(sessionId='persisted')))
        agent.session.append('turn/start',dict(turn=2));agent.session.append('turn/end',dict(turn=2,reason=dict(kind='completed')))
        record('after-terminal',await call('wait',dict(sessionId='persisted')))
        outsider=await ctx.agents.create(dict(sessionId='outsider',agentOptions=dict(provider='script',model='model')))
        ctx.emit('agent/error',dict(agent=outsider.agent,error=RuntimeError('unowned')));record('unowned',await call('wait',dict(sessionId='outsider')))
        child=await ctx.agents.create(dict(sessionId='child',meta=dict(parentSession='persisted',origin='subagent'),agentOptions=dict(provider='script',model='model')))
        child.agent.session.append('turn/start',dict(turn=1));child.agent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')));await child.dispose()
        record('resume-child',await call('resume',dict(sessionId='child')))
        await server.sessions['persisted'].dispose();record('stale',await call('wait',dict(sessionId='persisted')))
        await outsider.dispose();await server.shutdown();record('shutdown-resume',await call('resume',dict(sessionId='new')));record('shutdown-wait',await call('wait',dict(sessionId='persisted')))
        return json.loads(json.dumps(rows).replace(str(WORKSPACE).replace('\\','\\\\'),'<work>'))
    finally:await server.shutdown();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';(WORKSPACE/'child').mkdir(parents=True)
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_session.mts','Actual SDK server and v4 Session/Agent/WorkingDirectory/JSONL providers compare cold resume, identity and directory preservation, route selection, owned idle wait, failure retirement at a durable terminal, unknown/stale/subagent refusal and shutdown ordering. Generated event ids/timestamps outside these observations.',[Path(__file__).resolve(),ROOT/'dsh/sdk/server.py'],prepare=prepare)
