"""Source/Native Schedule tools through actual tool dispatch and scoped registries."""
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def cases():
    rows=[]
    for target in ['this_session','new_once','new']:
        rows.append(dict(name='create-'+target,tool='schedule_create',args=dict(title='提醒',prompt='work',rrule='rule',target=target,ignored=True)))
    rows.extend([dict(name='list',tool='schedule_list',args=dict(active=False,limit=4,offset=1,sessionId='ignored')),
        dict(name='list-default',tool='schedule_list',args={}),dict(name='view-missing',tool='schedule_view',args=dict(id='missing'))])
    for kind in ['rrule','cron','every','after','at','daily','weekly']:rows.append(dict(name='view-'+kind,tool='schedule_view',args=dict(id=kind)))
    for action,args in [('empty',{}),('all',dict(title='new',prompt='new',rrule='rule',target='new_once',active=False,expectedUpdatedAt='stamp')),('delete-patch',dict(action='delete',active=False)),('delete',dict(action='delete',expectedUpdatedAt='stamp'))]:
        rows.append(dict(name='edit-'+action,tool='schedule_edit',args=dict(dict(id='at',action='update'),**args)))
    for tool in ['schedule_create','schedule_list','schedule_view','schedule_edit']:
        args=next(copy.deepcopy(row['args']) for row in rows if row['tool']==tool)
        if tool=='schedule_edit':args['title']='edit'
        for mode in ['no-agent','delegated','internal','invalid_rule','invalid_selector']:
            rows.append(dict(name=tool+'-'+mode,tool=tool,args=args,mode=mode))
    return rows


def task(kind):
    result=dict(id=kind,kind=kind,title='提醒',prompt='work',scheduledAt='2030-01-02T03:04:05.000Z',target=dict(kind='session',sessionId='root'),status='active',createdAt='2029-01-01T00:00:00.000Z',updatedAt='2029-01-01T00:00:00.000Z',involvedSessionIds=['root'],executionActive=True,deliveryFloorEndsAt='secret',lastDelivery=dict(scheduledAt='2029-01-01T00:00:00.000Z',deliveredAt='2029-01-01T00:00:01.000Z',targetSessionId='root',messageId='secret'))
    result.update(dict(rrule=dict(rrule='DTSTART;TZID=Asia/Shanghai:20300101T000000\nRRULE:FREQ=DAILY'),cron=dict(expression='0 0 * * *',timeZone='Asia/Shanghai'),every=dict(everySeconds=60),after=dict(afterSeconds=60),at={},daily=dict(time='12:30',timeZone='Asia/Shanghai'),weekly=dict(time='12:30',timeZone='Asia/Shanghai',weekdays=[1,3]))[kind]);return result


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.schedule.tools_current import CurrentToolSchedule,DESCRIPTORS,target_help
    from dsh.schedule.domain_current import ScheduleInputError
    from dsh.core.scope import create_scope
    from dsh.core.tools import ToolExecutionInput
    from dsh.core.abort import NEVER_ABORTED
    fixture=await setup(WORKSPACE/'native',script=[]);ctx=fixture.ctx;requests=[];mode='';sections=[]
    async def invoke(name,*args):
        if mode=='internal':raise RuntimeError('private backend path')
        if mode in ('invalid_rule','invalid_selector'):raise ScheduleInputError(mode,'declared error')
        requests.append([name,*(args[:2] if name in ('create','edit') else args)])
        if name=='list':return dict(items=[task('at')],shown=1,total=1,limit=100,offset=0)
        if name=='view' and args[0]['id']=='missing':return dict(id='missing',code='schedule_not_found')
        if name=='edit' and args[0]['action']=='delete':return dict(id=args[0]['id'],deleted=True)
        return task(args[0]['id'] if name=='view' else 'at')
    schedule=SimpleNamespace(deliveryLimits=lambda:dict(newSessionIntervalSeconds=90))
    for name in ['create','list','view','edit']:
        async def call(*args,name=name):return await invoke(name,*args)
        setattr(schedule,name,call)
    ctx.provide('schedule',schedule);ctx.provide('agentPresets',SimpleNamespace(composedPreset=lambda _: 'selected-preset'))
    lease=await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')));agent=lease.agent
    scope=create_scope(ctx,agent);original=ctx.systemPrompt.section
    # Retain the registered callback while still exercising the real prompt registry.
    def section(spec):sections.append(spec);return original(spec)
    ctx.systemPrompt.section=section
    rows=[]
    try:
        fiber=await scope.ctx.plugin(CurrentToolSchedule)
        descriptors=[]
        for seconds in [60,90,120,7200]:
            value=copy.deepcopy(DESCRIPTORS);value['definitions'][0]['parameters']['properties']['target']['description']=target_help(seconds);descriptors.append(value)
        rows.append(dict(name='descriptors',value=descriptors))
        rows.append(dict(name='scope',outside=ctx.tools.get('schedule_create') is not None,inside=ctx.tools.get('schedule_create',agent) is not None,guidance=sections[-1]['text'](dict(scope=agent)),outsideGuidance=sections[-1]['text'](dict(scope=None))))
        # A global mount also permits the explicit absent-Agent refusal path.
        global_fiber=await ctx.plugin(CurrentToolSchedule)
        for index,row in enumerate(cases()):
            mode=row.get('mode','');agent.options.subagentDepth=1 if mode=='delegated' else 0
            before=len(requests);result=await ctx.tools.execute(ToolExecutionInput('call-'+str(index),row['tool'],row['args'],agent=None if mode=='no-agent' else agent,signal=NEVER_ABORTED))
            rows.append(dict(name=row['name'],value=dict(isError=result.is_error,value=result.value,content=result.content),requests=requests[before:],presentation=ctx.tools.get(row['tool'],agent).present_call(row['args'])))
        await global_fiber.dispose();await fiber.dispose()
        rows.append(dict(name='disposed',inside=ctx.tools.get('schedule_create',agent) is not None))
        return json.loads(json.dumps(rows))
    finally:await scope.dispose();await lease.dispose();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();data=output/'input.json'
    data.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=cases(),tasks={kind:task(kind) for kind in ['rrule','cron','every','after','at','daily','weekly']})),encoding='utf-8');return [data]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_tools.mts','Actual scoped tool dispatch, fixed Source descriptors at four limits, seven task variants, caller and error refusal, declared selector extraction, composed preset, withheld metadata, JSON rendering and generic presentations. Controlled Host service; durable service separately verified.',[Path(__file__).resolve(),ROOT/'dsh/schedule/tools_current.py',ROOT/'dsh/schedule/tools_current.json',ROOT/'scripts/oracles/rc022_schedule_definition.mts'],prepare=prepare)
