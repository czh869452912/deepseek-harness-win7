"""Pair the candidate controller's actual Cordis initialization and teardown."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from scripts.rc022_inbox_readers_probe import message
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.host.connection.peer import Peer
    directory=(workspace or WORKSPACE)/'native-work';directory.mkdir()
    fixture=await setup((workspace or WORKSPACE)/'native',directory=directory);ctx=fixture.ctx;rows=[];events=[];resolver=[];streams=[];gate=asyncio.Event();entered=asyncio.Event();mounting=None
    try:
        for plugin in (CurrentTypertRegistry,RemoteAccessService,AuthorizedGatewayService):await ctx.plugin(plugin)
        ctx.set_service('agentDefaultModel',NS(currentSelection=lambda:dict(provider='script',model='model')))
        ctx.set_service('attachments',NS(imageLimits=dict(maxImageBytes=1,maxImagesPerMessage=1,maxMessageImageBytes=1,maxImagePixels=1,maxImageDimension=1,mediaTypes=['image/png'])))
        def register(callback):
            resolver.append(callback)
            return lambda:resolver.remove(callback)
        ctx.set_service('fileUploads',NS(registerAgentResolver=register))
        archived=[];ctx.set_service('workspaceRegistry',NS(archivedSessionIds=archived,list=lambda:[]))
        ctx.on('api-session/added',lambda value:events.append(dict(type='added',sessionId=value['sessionId'],agentAvailable=value['agentAvailable'])))
        ctx.on('api-session/removed',lambda identity:events.append(dict(type='removed',sessionId=identity)))
        handle=await ctx.agents.create(dict(sessionId='boot',meta=dict(cwd=str(directory)),agentOptions=dict(provider='script',model='model')));agent=handle.agent
        original=ctx.sessionProjections.register;first=[True]
        async def registration(*args,**kwargs):
            if first[0]:first[0]=False;entered.set();await gate.wait()
            return await original(*args,**kwargs)
        ctx.sessionProjections.register=registration
        async def mount():return await ctx.plugin(AuthorizedSessionController,dict(nativeOpen=False,listWorkSliceMs=4))
        mounting=asyncio.ensure_future(mount());await asyncio.wait_for(entered.wait(),5)
        ctx.emit('agent/assistant-stream',dict(agent=agent,frame=dict(type='start',attemptId='boot-attempt',revision=1,turn=1,step=1)))
        gate.set();provider=await mounting;ctx.sessionProjections.register=original;api=ctx.sessionController
        opening=api.follow(dict(address=dict(kind='session',sessionId='boot'),assistantStream=True),fixture.signal);streams.append(opening)
        value=await opening.__anext__();rows.append(dict(name='opening-captured-during-init',baseline=value['assistantStream'],resolvers=len(resolver),budget=api.list_state.work_slice_ms,hasLegacyHistory=hasattr(api,'history')));await opening.aclose()
        owner=Peer(ctx,dict(principal=dict(kind='owner')))
        async def invoke(method,request):return await ctx.typertGateway.invoke(dict(namespace='session',method=method,args=dict(request=request),peer=owner,signal=fixture.signal))
        rows.append(dict(name='state-through-gateway',value=await invoke('state',dict(sessionId='boot'))))
        rows.append(dict(name='wait-through-gateway',reason=(await invoke('wait',dict(sessionId='boot')))['reason']))
        rows.append(dict(name='upload-resolver',same=await resolver[0]('boot') is agent))
        created=await ctx.agents.create(dict(sessionId='availability',meta=dict(cwd=str(directory)),agentOptions=dict(provider='script',model='model')))
        await created.dispose();rows.append(dict(name='availability-events',value=list(events)));events.clear()
        control=api.control(fixture.signal);streams.append(control);value=await control.__anext__();rows.append(dict(name='projection-control',type=value['type'],keys=sorted(value['value']),sessions=sorted(value['value']['projections'])));await control.aclose()
        archived.append('boot');agent.followup(message('blocked'));await asyncio.wait_for(agent.whenIdle(),5)
        records=agent.session.snapshotEvents();rows.append(dict(name='archive-stops-model-step',requests=sum(event['type']=='request/header' for event in records),ending=[event['data']['reason']['kind'] for event in records if event['type']=='turn/end']))
        await provider.dispose();before=len(events);ctx.sessions.create('after-unload',meta=dict(cwd=str(directory)))
        rows.append(dict(name='unloaded',resolvers=len(resolver),newEvents=len(events)-before,baselines=len(api.history_reads.streamsListener.streams),serviceGone=ctx.get('sessionController') is None))
        return json.loads(json.dumps(rows))
    finally:
        gate.set()
        if mounting is not None:await asyncio.gather(mounting,return_exceptions=True)
        for stream in streams:await stream.aclose()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_composition.mts','Actual Cordis controller/Agent/Session/FS/WorkingDirectory/Typert/Gateway composition: Assistant frames during awaited registration, configured list budget, passive Remote state/wait, upload Agent resolver, live availability notifications, projection-only control, archived ordinary execution admission and provider teardown. Deployment model defaults, attachment limits, upload resolver and archive membership are controlled collaborators. Native desktop/file/media behavior remains separately scoped.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_authorized.py',ROOT/'dsh/api/archived_session_gate.py',ROOT/'dsh/api/session_list_authorized.py'],prepare=prepare)
