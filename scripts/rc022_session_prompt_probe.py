"""Pair trusted caller metadata and durable explicit retry admission."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import TypertRemoteService
    from dsh.api.session_authorized import AuthorizedSessionController
    from dsh.api.session_commands_authorized import AuthorizedSessionCommands
    from dsh.host.connection.peer import Peer
    from dsh.llm.llm_service import LlmError
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];requests=[];resolves=[];admissions=[]
    class Script(ScriptAdapter):
        async def stream(self,request):
            requests.append(request)
            if len(requests)<=2:raise LlmError('busy','SERVER')
            yield dict(type='block-start',index=0,blockType='text')
            yield dict(type='text-delta',index=0,text='done')
            yield dict(type='block-end',index=0,block=dict(type='text',text='done'))
            yield dict(type='finish',reason=dict(kind='stop'))
    try:
        await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
        ctx.typert.resources.register('session',dict(field='sessionId'))
        ctx.llm.registerAdapter(['failure'],Script({}))
        async def resolve(identity):resolves.append(identity);return dict(agent=ctx.agents.get(identity))
        async def serialize(agent,callback):return await callback()
        async def admit(parts):admissions.append(parts);return parts
        ctx.set_service('attachments',NS(admitPromptContent=admit))
        ctx.set_service('fileUploads',NS(resolve=lambda *_:None,bindPrompt=lambda *_:NS(commit=lambda:None,dispose=lambda:None)))
        api=AuthorizedSessionController.__new__(AuthorizedSessionController);TypertRemoteService.__init__(api,ctx,'sessionController',dict(namespace='session'))
        api.commands=AuthorizedSessionCommands(ctx,NS(resolveAgent=resolve,serializeImageAdmission=serialize),'C:/work');await api.commands.initialize()
        agent=(await ctx.agents.create(dict(sessionId='session',agentOptions=dict(provider='failure',model='model')))).agent
        ctx.remoteAccess.registerPolicy('guest',dict(bindings=lambda *_:[dict(resource=dict(kind='session',id='session'),role=dict(actions=['session/prompt']))]))
        owner=Peer(ctx,dict(principal=dict(kind='owner')));guest=Peer(ctx,dict(principal=dict(kind='guest',id='g')))
        async def submit(name,peer,content,identity=None,**options):
            before=(len(resolves),len(admissions),len(requests))
            request=dict(sessionId='session',requestId=identity or name,content=content,mode='queue',**options)
            try:result=dict(value=await ctx.typertGateway.invoke(dict(namespace='session',method='prompt',args=dict(request=request),peer=peer,signal=fixture.signal)))
            except Exception as error:result=dict(error=dict(code=error.code,details=error.details))
            await agent.whenIdle()
            rows.append(dict(name=name,**result,resolved=len(resolves)-before[0],admitted=len(admissions)-before[1],requests=len(requests)-before[2]))
        await submit('fresh-empty',guest,[])
        await submit('whitespace',guest,[dict(type='text',text=' \t')])
        await submit('bad-zone',guest,[dict(type='text',text='task')],clientTimeZone='not/a-zone')
        await submit('original',owner,[dict(type='text',text='original task')])
        rows.append(dict(name='first-ending',value=api.commands.continuation.stateOf(agent.session)['ending'] is not None))
        await submit('retry-1',guest,[],clientTimeZone='Asia/Shanghai')
        await submit('duplicate-retry',guest,[],identity='retry-1',clientTimeZone='Asia/Shanghai')
        await submit('retry-2',guest,[])
        await submit('after-completion',guest,[])
        await submit('duplicate-original',owner,[dict(type='text',text='original task')],identity='original')
        messages=[event['data'] for event in agent.session.snapshotEvents() if event['type']=='user/message']
        rows.append(dict(name='durable-messages',values=[dict(content=message['content'],source=message['source']) for message in messages],endings=[event['data']['reason']['kind'] for event in agent.session.snapshotEvents() if event['type']=='turn/end'],requests=[[message['content'] for message in request['messages'] if message['role']=='user'] for request in requests]))
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_prompt.mts','Actual Gateway prompt face and actual command/AgentLoop/Session/projection: fresh/whitespace/time-zone refusal before resolution, owner versus guest durable source, two recoverable failures, empty retries and first-insertion deduplication through completion. Attachment admission/upload binding are controlled collaborators; full controller boot and upload provider remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_authorized.py',ROOT/'dsh/api/session_commands_authorized.py',ROOT/'dsh/api/session_continuation.py'],prepare=prepare)
