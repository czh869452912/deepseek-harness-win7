"""Pair Session read filtering with actual Gateway and v4 projection streams."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def project(frame):
    if frame['type']=='baseline':
        return dict(type='baseline',keys=sorted(frame['value']['projections']),values={key:value['values']['accessProbe'] for key,value in frame['value']['projections'].items()})
    return dict(type=frame['type'],sessionId=frame['sessionId'],seq=frame['seq'],changes=[change for change in frame['changes'] if change['key']=='accessProbe'])


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import TypertRemoteService
    from dsh.api.session_authorized import AuthorizedSessionController,ProjectionSessionControl
    from dsh.host.connection.peer import Peer
    from dsh.core.abort import AbortController
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];streams=[]
    try:
        await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
        await ctx.sessionProjections.register(dict(key='accessProbe',stateVersion=1,stateSchema=lambda value:value,init=lambda *_:0,
            apply=lambda state,event:event['data']['value'] if event['type']=='access/probe' else state,
            wire=dict(viewSchema=lambda value:value,view=lambda state:state)))
        agents=[(await ctx.agents.create(dict(sessionId=identity,agentOptions=dict(provider='script',model='model')))).agent for identity in ('shared','hidden')]
        api=AuthorizedSessionController.__new__(AuthorizedSessionController)
        TypertRemoteService.__init__(api,ctx,'sessionController',dict(namespace='session'))
        calls=[];items=[dict(sessionId='hidden',title='Hidden'),dict(sessionId='shared',title='Shared')]
        async def listing(signal):calls.append('list');return items
        async def search(query,signal):calls.append('search');return dict(items=[dict(sessionId=item['sessionId'],snippet=item['title']) for item in items],hasMore=True)
        api.list_state=NS(list=listing,search=search)
        api.control_state=ProjectionSessionControl(ctx)
        held=['shared'];global_access=[True]
        def bindings(*_):
            actions=['session/list','session/search','session/control']
            return ([dict(resource=dict(kind='global'),role=dict(actions=actions))] if global_access[0] else [])+[dict(resource=dict(kind='session',id=identity),role=dict(actions=actions)) for identity in held]
        ctx.remoteAccess.registerPolicy('guest',dict(bindings=bindings))
        owner=Peer(ctx,dict(principal=dict(kind='owner')));guest=Peer(ctx,dict(principal=dict(kind='guest',id='g')))
        async def call(peer,method,args):return await ctx.typertGateway.invoke(dict(namespace='session',method=method,args=args,peer=peer,signal=fixture.signal))
        for label,peer in [('owner',owner),('guest',guest)]:
            rows.append(dict(name=label+'-list',value=await call(peer,'list',dict(_request={}))))
            rows.append(dict(name=label+'-search',value=await call(peer,'search',dict(request=dict(query='hit')))))
        global_access[0]=False;before=len(calls)
        try:await call(guest,'list',dict(_request={}))
        except Exception as error:rows.append(dict(name='global-refusal',code=error.code,reads=len(calls)-before))
        global_access[0]=True;signals=[AbortController(),AbortController()]
        for label,peer,controller in [('owner',owner,signals[0]),('guest',guest,signals[1])]:
            stream=await ctx.typertGateway.stream(dict(namespace='session',method='control',args={},peer=peer,signal=controller.signal));streams.append(stream)
            rows.append(dict(name=label+'-baseline',value=project(await stream.__anext__())))
        agents[1].session.append('access/probe',dict(value=1));agents[0].session.append('access/probe',dict(value=2))
        rows.append(dict(name='owner-updates',value=[project(await streams[0].__anext__()),project(await streams[0].__anext__())]))
        rows.append(dict(name='guest-update',value=project(await streams[1].__anext__())))
        held[:]=['hidden'];agents[0].session.append('access/probe',dict(value=3));agents[1].session.append('access/probe',dict(value=4))
        rows.append(dict(name='changed-grant',value=project(await streams[1].__anext__())))
        for controller in signals:controller.abort()
        ended=[]
        for stream in streams:
            try:await stream.__anext__();ended.append(False)
            except StopAsyncIteration:ended.append(True)
            except Exception as error:ended.append(dict(error=error.code))
        rows.append(dict(name='cancelled',ended=ended,subscriptions=len(api.control_state.streams),inputs=items))
        return json.loads(json.dumps(rows))
    finally:
        for stream in streams:await stream.aclose()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_access.mts','Actual Session Remote wrappers through Gateway with controlled list/search IO, plus actual v4 Agent/Session/Projection control streams, per-Peer baseline/update filtering, live grant changes, pre-read global denial and cancellation. Full SessionController boot and other methods remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_authorized.py',ROOT/'dsh/api/session_control_current.py',ROOT/'dsh/api/session_current.py'],prepare=prepare)
