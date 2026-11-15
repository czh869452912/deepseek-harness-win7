"""Actual conditional Team tools, prompts, naming and pipeline results."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    def call(name,args):return dict(op='execute',name='team_task_'+name,args=args)
    return [dict(op='visible',caller='none'),dict(op='visible'),dict(op='prompt'),dict(op='enable',value=True),
        dict(op='visible'),dict(op='visible',caller='worker'),dict(op='prompt'),
        call('create',dict(subject='First',description='Details',write_scopes=['./src/'])),
        call('create',dict(subject='Second',description='Details')),
        call('create',dict(subject='Third',description='Details',blocked_by=['task-1'])),
        call('update',dict(task_id='task-1',expected_revision=1,action='reassign',owner='worker')),
        call('get',dict(task_id='task-1')),call('list',dict(owner='worker')),call('list',dict(unowned=True)),
        call('list',dict(ready=True,cursor=0,limit=1)),call('list',dict(cursor=1,limit=1)),
        call('list',dict(owner='worker',unowned=False)),call('list',dict(cursor=-1)),call('list',dict(limit=101)),
        call('get',dict(task_id=1)),call('update',dict(task_id='task-1',expected_revision=1,action='claim')),
        dict(op='held-disable'),dict(op='visible'),call('list',{}),dict(op='enable',value=True),
        dict(op='cold'),dict(op='visible',caller='worker'),dict(op='prompt',caller='worker'),
        dict(op='unload'),dict(op='visible'),dict(op='prompt'),dict(op='removed-config')]


async def observe(workspace):
    from dsh.core.tools import ToolExecutionInput
    from dsh.core.scope import scope_of
    from dsh.team.service import TeamPlugin
    from dsh.team.tools import TeamToolsPlugin,DEFINITIONS
    from scripts.rc022_subagent_fixture import setup
    fixture=await setup(workspace);ctx=fixture.ctx;signal=fixture.signal;rows=[dict(kind='metadata',data=DEFINITIONS)]
    try:
        await ctx.plugin(TeamPlugin);owner=await ctx.plugin(TeamToolsPlugin)
        parent=(await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))).agent
        receipt=await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId='child',name='worker',label='Task',
            prompt=[dict(type='text',text='Task')],signal=signal,delivery='caller'))
        worker=ctx.agents.get('child');actors=dict(root=parent,worker=worker,none=None);inbox=[]
        ctx.on('agent/inbox/inserted',lambda payload:inbox.append(payload['agent'].id))
        async def resolved(agent):return await ctx.tools.resolve(dict(agent=agent,signal=signal,modelSelection=dict(provider='script',model='model')))
        async def execute(name,args,agent,toolset=None):
            owned=toolset is None
            if owned:toolset=await resolved(agent)
            try:
                result=await ctx.tools.execute(ToolExecutionInput('call',name,args,agent=agent,signal=signal,toolSet=toolset))
                return dict(isError=result.is_error,content=result.content,value=None if result.is_error else result.value)
            finally:
                if owned:toolset.dispose()
        for command in cases():
            op=command['op'];agent=actors[command.get('caller','root')];row=dict(op=op)
            if op=='visible':
                toolset=await resolved(agent)
                try:row['names']=sorted(tool['name'] for tool in ctx.tools.schemas(agent,toolset) if tool['name'].startswith('team_'))
                finally:toolset.dispose()
            elif op=='prompt':
                assembly=await ctx.systemPrompt.assemble(dict(agent=agent,scope=scope_of(agent.ctx) if agent is not None else None))
                row['policy']=next((section['text'] for section in assembly['sections'] if section['name']=='team:policy'),'')
            elif op=='enable':await ctx.agentTeams.setEnabled(parent,command['value'],signal)
            elif op=='execute':row.update(await execute(command['name'],command['args'],agent))
            elif op=='held-disable':
                toolset=await resolved(parent)
                try:
                    await ctx.agentTeams.setEnabled(parent,False,signal)
                    row.update(await execute('team_task_get',dict(task_id='task-1'),parent,toolset))
                finally:toolset.dispose()
            elif op=='cold':await receipt['dispose']()
            elif op=='unload':await owner.dispose()
            elif op=='removed-config':
                try:await ctx.plugin(TeamToolsPlugin,dict(freshProvider='spawn'))
                except Exception as error:row['error']=str(error)
            rows.append(row)
        rows.append(dict(op='effects',inbox=inbox,tasks=ctx.agentTeams.listTasks(parent)))
    finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8')
    inputs=output/'cases.json';inputs.write_text(json.dumps(cases()),encoding='utf-8');return [path,inputs]


if __name__=='__main__':
    probe.native=lambda:observe(WORKSPACE/'native')
    probe.main('rc022_team_tools.mts','Exact upstream tool schemas/guidance plus actual pipeline: per-Agent admission, named task owner/filter, pagination, schema/domain errors, held admission after mode off, detached child and reversible tool/prompt disposal.',
        [Path(__file__).resolve(),ROOT/'dsh/team/tools.py',ROOT/'dsh/team/tool_definitions.json',ROOT/'scripts/oracles/rc022_team_tool_metadata.mts'],prepare=prepare)
