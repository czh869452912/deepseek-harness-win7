"""Instruction plugin through actual inbox, scoped pre-step and tool execution."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.context.agent_instructions.runtime_authorized import AuthorizedAgentInstructionsPlugin
    from dsh.core.agent_dispatch_current import agent_events
    from dsh.core.tools import ToolExecutionInput
    from dsh.fs.tools_authorized import AuthorizedToolFs
    from dsh.llm.message import create_user_message
    base=(workspace or WORKSPACE)/'native';project=base/'project';nested=project/'pkg';home=base/'home';shared=base/'shared'
    for path in (nested,home,shared):path.mkdir(parents=True,exist_ok=True)
    def write(path,text):path.write_bytes(text.encode('utf-8'))
    for path,text in [(project/'.git','marker'),(project/'AGENTS.md','project rules'),(nested/'AGENTS.md','nested rules'),
            (nested/'file.txt','content'),(home/'AGENTS.md','global rules'),(shared/'AGENTS.md','shared rules')]:write(path,text)
    saved={key:os.environ.get(key) for key in ('DSH_HOME','DSH_AGENTS_HOME')}
    os.environ.update(DSH_HOME=str(home),DSH_AGENTS_HOME=str(shared))
    fixture=await setup(base/'sessions',directory=project);ctx=fixture.ctx;rows=[];handle=None;counter=0
    try:
        await ctx.plugin(AuthorizedToolFs)
        plugin=await ctx.plugin(AuthorizedAgentInstructionsPlugin,dict(maxBytes=65536))
        handle=await ctx.agents.create(dict(sessionId='runtime',meta=dict(cwd=str(project)),agentOptions=dict(provider='script',model='model')))
        agent=handle.agent;dispatch=agent_events(ctx,agent)
        def user(text):return create_user_message(dict(content=[dict(type='text',text=text)],source=dict(kind='user')))
        def clean(value):
            if isinstance(value,dict):return {key:clean(item) for key,item in value.items() if key!='id'}
            if isinstance(value,(list,tuple)):return [clean(item) for item in value]
            return value
        def pending():return [message for message in agent.inbox.nextStep if message['source']['kind']=='agent-instructions']
        async def step(label,claimed=None,kind='reject',step_number=1):
            claimed=[] if claimed is None else claimed
            decision=dict(kind=kind,**(dict(messages=claimed+[user('driver')],startsRequestSeries=True) if kind!='reject' else {}))
            result=await dispatch.waterfall('agent/pre-step',dict(turn=1,step=step_number,messages=claimed,signal=fixture.signal),lambda:decision)
            rows.append(dict(name=label,decision=clean(result),pending=clean(pending())))
            return result
        await step('rejected-first');first=pending()[0]
        await step('rejected-reuses-pending');rows.append(dict(name='pending-identity',same=pending()[0] is first))
        entered=await step('entered-order',[user('direct')],kind='enter')
        for message in entered['messages']:agent.session.append('user/message',message,surface_op='append')
        await step('already-visible',kind='enter')
        async def call(name,args,parent=None):
            nonlocal counter
            counter+=1
            return await ctx.tools.execute(ToolExecutionInput('call-'+str(counter),name,args,agent=agent,signal=fixture.signal,parent=parent))
        await call('read',dict(file_path='pkg/file.txt'));await step('idle-tool-touch')
        for message in pending():agent.session.append('user/message',message,surface_op='append');agent.inbox.remove(message['id'])
        agent.session.append('turn/start',dict(turn=1));agent.session.append('step/start',dict(turn=1,step=1))
        write(nested/'AGENTS.md','nested changed during step')
        result=await call('read',dict(file_path='pkg/file.txt'));await asyncio.sleep(0)
        rows.append(dict(name='open-step-defers',pending=clean(pending()),isError=result.isError))
        agent.session.append('step/end',dict(turn=1,step=1));await step('closed-step-projects')
        for message in pending():agent.session.append('user/message',message,surface_op='append');agent.inbox.remove(message['id'])
        inside=[]
        async def outer(args,execution):
            await call('read',dict(file_path='pkg/file.txt'),execution.token)
            await asyncio.sleep(0);inside.append(len(pending()));raise RuntimeError('outer failed after successful child')
        ctx.tools.register(dict(name='outer',description='',parameters=dict(type='object'),
            output=dict(schema=dict(type='string'),render=lambda a,v:[dict(type='text',text=v)]),execute=outer))
        write(nested/'AGENTS.md','nested changed in successful child of failed outer')
        result=await call('outer',{});await step('outer-completion-projects-child')
        rows.append(dict(name='parent-boundary',inside=inside,outerError=result.isError))
        for message in pending():agent.session.append('user/message',message,surface_op='append');agent.inbox.remove(message['id'])
        write(nested/'AGENTS.md','failed read must not project this')
        await call('read',dict(file_path='pkg/missing.txt'));await asyncio.sleep(0)
        rows.append(dict(name='failed-tool-no-projection',pending=clean(pending())))
        await ctx.workingDirectory.set(agent,'pkg',fixture.signal)
        await step('directory-replacement')
        rows.append(dict(name='header-preserved',cwd=agent.session.header.cwd,current=ctx.workingDirectory.get(agent.session)))
        for message in pending():agent.session.append('user/message',message,surface_op='append');agent.inbox.remove(message['id'])
        for name in ('alpha','beta'):
            (nested/name).mkdir();write(nested/name/'AGENTS.md',name+' nested rule');write(nested/name/'file.txt','content')
        await asyncio.gather(*[call('read',dict(file_path=name+'/file.txt')) for name in ('alpha','beta')])
        await step('serialized-concurrent-projections')
        await plugin.dispose()
        before=len(agent.session.snapshotEvents());await call('read',dict(file_path='file.txt'));await asyncio.sleep(0)
        rows.append(dict(name='unloaded-no-projection',inboxEvents=sum(event['type']=='agent/inbox/spliced' for event in agent.session.snapshotEvents()[before:])))
        def normalize(value):
            if isinstance(value,str) and str(project) in value:return value.replace(str(project),'<work>')
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            if isinstance(value,list):return [normalize(item) for item in value]
            return value
        return normalize(rows)
    finally:
        if handle is not None:await handle.dispose()
        await ctx.fiber.dispose()
        for key,value in saved.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_instruction_runtime.mts','Actual candidate plugin with Session/Inbox, scoped pre-step and FsLocal tools: pending baseline reuse, insertion order, visible suppression, successful tool projection, open-step deferral, nested child commit at parent completion including parent failure, failed-tool filtering, directory replacement and reversible unload. Message IDs omitted; owned project roots projected to <work>. Driver decisions controlled; no live model request.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/context/agent_instructions/runtime_authorized.py','dsh/context/agent_instructions/state_authorized.py','dsh/context/agent_instructions/files_authorized.py')],prepare=prepare)
