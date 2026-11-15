"""Actual SDK server directory RPC over real Session/directory providers."""
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
    fixture=await setup(WORKSPACE/'sessions-native',script=[],directory=WORKSPACE);ctx=fixture.ctx
    server=HarnessSdkJsonRpcServer(ctx,SimpleNamespace(notify=lambda *_:None));rows=[]
    async def call(method,params):
        try:return dict(value=await server.handle_request('session/working-directory/'+method,params))
        except Exception as error:return dict(error=getattr(error,'message',str(error)),name=getattr(error,'name','TypeError' if isinstance(error,TypeError) else 'Error'))
    def record(name,result):
        rows.append(dict(name=name,result=result,agents=[agent.id for agent in ctx.agents.list()]))
    try:
        record('before-get',await call('get',dict(sessionId='a')))
        record('before-set',await call('set',dict(sessionId='a',path='child')))
        await server.initialize(dict(cwd=str(WORKSPACE),provider='script',model='model'))
        for name,method,params in [('bad-id-empty','get',dict(sessionId='')),('bad-id','get',{}),('bad-id-type','get',dict(sessionId=3)),('bad-path','set',dict(sessionId='a',path=3))]:record(name,await call(method,params))
        record('initial',await call('get',dict(sessionId='a',extra='ignored')))
        record('relative',await call('set',dict(sessionId='a',path='child')))
        record('isolation',await call('get',dict(sessionId='b')))
        await asyncio.get_running_loop().run_in_executor(None,(WORKSPACE/'child').rmdir)
        record('recovered',await call('get',dict(sessionId='a')))
        (WORKSPACE/'child').mkdir()
        record('absolute',await call('set',dict(sessionId='a',path=str(WORKSPACE/'child'))))
        record('missing',await call('set',dict(sessionId='a',path='missing')))
        agent=ctx.agents.get('a')
        rows.append(dict(name='durable',origin=agent.session.header.cwd,current=ctx.workingDirectory.get(agent.session),
            changes=[event['data'] for event in agent.session.snapshotEvents() if event['type']=='working-directory/change']))
        await server.sessions['a'].dispose();record('stale',await call('get',dict(sessionId='a')))
        record('concurrent',dict(value=await asyncio.gather(call('get',dict(sessionId='c')),call('get',dict(sessionId='c')))))
        await server.shutdown();record('shutdown',await call('get',dict(sessionId='new')))
        return json.loads(json.dumps(rows).replace(str(WORKSPACE).replace('\\','\\\\'),'<work>'))
    finally:await server.shutdown();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';(WORKSPACE/'child').mkdir(parents=True)
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_directory.mts','Actual SDK working-directory RPC and actual WorkingDirectory/FS/Agent/Session providers compare initialization admission, exact RPC type diagnostics, unknown Session creation, relative/absolute changes, origin isolation, missing directory recovery, durable events, retired Agent refusal, concurrent identity reuse and shutdown admission. Generated IDs/timestamps are excluded; actual paths are projected to one physical owned root.',[Path(__file__).resolve(),ROOT/'dsh/sdk/server.py'],prepare=prepare)
