"""Scoped model Schedule tools over the current Host management service."""
import copy
import json
from pathlib import Path

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.subagent.composition import delegation_depth
from dsh.typert.stores import field
from .domain_current import ScheduleInputError,format_schedule_local_time

DESCRIPTORS=json.loads((Path(__file__).parent/'tools_current.json').read_text(encoding='utf-8'))
CALLER_ERRORS=['subagent_session','internal_error']
CREATE_ERRORS=['invalid_prompt','invalid_rule','invalid_time_zone','not_future','frequency_too_high']+CALLER_ERRORS
PATCH_FIELDS=['title','prompt','rrule','target','active']


def model_task(task):
    result={key:value for key,value in task.items() if key not in ('involvedSessionIds','createdAt','executionActive','deliveryFloorEndsAt','lastDelivery')}
    result['scheduledAtLocal']=format_schedule_local_time(task,task['scheduledAt'])
    if 'lastDelivery' in task:
        result['lastDelivery']={key:task['lastDelivery'][key] for key in ('scheduledAt','deliveredAt','targetSessionId')}
    return result


def target_for(agent,choice):
    if choice=='this_session':return dict(kind='session',sessionId=agent.session.id)
    spec={};cwd=field(agent.session.header,'cwd')
    if cwd is not None:spec['cwd']=cwd
    presets=agent.ctx.get('agentPresets');preset=presets.composedPreset(agent.ctx) if presets is not None else None
    if preset is not None:spec['agentPreset']=preset
    return dict(kind=choice,create=spec)


def target_help(seconds):
    seconds=int(seconds)
    spacing='' if seconds<=60 else ', at most once every {} {}'.format(int(seconds//60) if seconds%60==0 else seconds,'minutes' if seconds%60==0 else 'seconds')
    return ('this_session delivers to this session; new_once delivers to the same new session every time, opened at the first delivery; '
        'new opens a different new session for every delivery'+spacing+'. New sessions use this session\'s working directory and preset. '
        'With this_session or new_once, a delivery waits until the previous one finishes, and only the latest occurrence that passed meanwhile is delivered. '
        'Use this_session for reminders and for follow-ups to this conversation; use new_once or new for independent work, such as a recurring report, '
        'and whenever the user asks for a new conversation.')


async def run_for_caller(execution,codes,operation):
    agent=execution.agent
    if agent is None:return dict(code='internal_error',message='The schedule operation failed.')
    if delegation_depth(agent)>0:return dict(code='subagent_session',message='A delegated subagent cannot use scheduled tasks.')
    try:return await await_callback_result(operation(agent))
    except BaseException as error:
        if isinstance(error,ScheduleInputError) and error.code in codes:return dict(code=error.code,message=str(error))
        return dict(code='internal_error',message='The schedule operation failed.')


class CurrentToolSchedule(Plugin):
    name='tool-schedule'
    inject=['tools','systemPrompt']

    def apply(self,ctx):ctx.inject(['schedule'],self.register)

    def register(self,ctx):
        def guidance(options):
            scope=field(options,'scope')
            return DESCRIPTORS['guidance'] if ctx.tools.get('schedule_create',scope) is not None or ctx.tools.get('schedule_edit',scope) is not None else ''
        ctx.systemPrompt.section(dict(name='tool:schedule',order=ctx.systemPrompt.getSectionOrder('TOOL_SCHEDULE'),text=guidance))
        async def create(args,execution):
            async def operation(agent):
                task=await await_callback_result(ctx.schedule.create(dict(title=args['title'],prompt=args['prompt'],timing=dict(kind='rrule',rrule=args['rrule']),target=target_for(agent,args['target'])),agent.session.id,execution.signal))
                return model_task(task)
            return await run_for_caller(execution,CREATE_ERRORS,operation)
        async def listing(args,execution):
            async def operation(agent):
                page=await await_callback_result(ctx.schedule.list({key:args[key] for key in ('active','limit','offset') if key in args}))
                return dict(page,items=[model_task(task) for task in page['items']])
            return await run_for_caller(execution,['invalid_rule']+CALLER_ERRORS,operation)
        async def view(args,execution):
            async def operation(agent):
                result=await await_callback_result(ctx.schedule.view(dict(id=args['id'])))
                return model_task(result) if 'kind' in result else result
            return await run_for_caller(execution,CALLER_ERRORS,operation)
        async def edit(args,execution):
            async def operation(agent):
                request=dict(id=args['id'],action=args['action'])
                if 'expectedUpdatedAt' in args:request['expectedUpdatedAt']=args['expectedUpdatedAt']
                if args['action']=='delete':
                    if any(key in args for key in PATCH_FIELDS):raise ScheduleInputError('invalid_selector','delete accepts only id, action, and expectedUpdatedAt.')
                else:
                    patch={key:args[key] for key in ('title','prompt') if key in args}
                    if 'rrule' in args:patch['timing']=dict(kind='rrule',rrule=args['rrule'])
                    if 'target' in args:patch['target']=target_for(agent,args['target'])
                    if 'active' in args:patch['active']=args['active']
                    if not patch:raise ScheduleInputError('invalid_selector','update requires at least one of title, prompt, rrule, target, or active.')
                    request['patch']=patch
                result=await await_callback_result(ctx.schedule.edit(request,agent.session.id,execution.signal))
                return model_task(result) if 'kind' in result else result
            return await run_for_caller(execution,['invalid_selector']+CREATE_ERRORS,operation)
        def present(args,name):
            title,kind={'schedule_create':('Create scheduled task','other'),'schedule_list':('List scheduled tasks','read'),'schedule_view':('View scheduled task','read'),'schedule_edit':('Delete scheduled task' if args.get('action')=='delete' else 'Edit scheduled task','other')}[name]
            result=dict(card='generic',title=title,kind=kind)
            key='title' if name=='schedule_create' else 'id'
            if name!='schedule_list' and key in args:result['rawInput']=args[key]
            return result
        execute=dict(schedule_create=create,schedule_list=listing,schedule_view=view,schedule_edit=edit)
        for raw in DESCRIPTORS['definitions']:
            definition=copy.deepcopy(raw);name=definition['name'];schema=definition.pop('outputSchema')
            if name=='schedule_create':definition['parameters']['properties']['target']['description']=target_help(ctx.schedule.deliveryLimits()['newSessionIntervalSeconds'])
            definition.update(execute=execute[name],output=dict(schema=schema,render=lambda args,value:[dict(type='text',text=stringify_json(value))]),presentCall=lambda args,name=name:present(args,name))
            if name in ('schedule_list','schedule_view'):definition['isConcurrencySafe']=lambda *_:True
            ctx.tools.register(definition)
