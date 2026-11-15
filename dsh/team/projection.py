"""Version-seven Lead-log Team projection; retired roster/mailbox records are inert."""
import math
import re
import weakref
from dsh.team.task_graph import assert_task_graph_candidate,project_task_view

MAX_SAFE=9007199254740991
TASK_NUMBER=re.compile(r'^task-([0-9]+)$')


class TaskCollection(list):
    """Weak-referenceable persistent collection used by the client view cache."""


def safe_integer(value,minimum=0):
    return type(value) in (int,float) and math.isfinite(value) and minimum<=value<=MAX_SAFE and value==int(value)


def nonempty(value):
    return isinstance(value,str) and len(value)>0


def task_id(value):
    if not nonempty(value):return False
    match=TASK_NUMBER.fullmatch(value)
    return match is None or int(match[1])<=MAX_SAFE


def parse_task(value):
    if (not isinstance(value,dict) or set(value)-{'id','revision','subject','description','status','ownerId','ownerName','blockedBy','writeScopes'}
            or not task_id(value.get('id')) or not safe_integer(value.get('revision'),1)
            or not isinstance(value.get('subject'),str) or not isinstance(value.get('description'),str)
            or value.get('status') not in ('pending','in_progress','completed','deleted')
            or not isinstance(value.get('blockedBy'),list) or not all(task_id(item) for item in value['blockedBy'])
            or not isinstance(value.get('writeScopes'),list) or not all(isinstance(item,str) for item in value['writeScopes'])
            or 'ownerId' in value and not nonempty(value['ownerId'])
            or 'ownerName' in value and (not nonempty(value['ownerName']) or 'ownerId' not in value)):
        raise ValueError('invalid Team task')
    return dict(value,blockedBy=list(value['blockedBy']),writeScopes=list(value['writeScopes']))


def empty_team_state(root_id,inherited_event_count=0):
    return dict(inheritedEventCount=inherited_event_count,id=root_id,tasks=TaskCollection(),nextTaskNumber=1)


def parse_state(value):
    if (not isinstance(value,dict) or set(value)-{'inheritedEventCount','enabled','id','tasks','nextTaskNumber','failure'}
            or not safe_integer(value.get('inheritedEventCount')) or not nonempty(value.get('id'))
            or not isinstance(value.get('tasks'),list) or not safe_integer(value.get('nextTaskNumber'),1)
            or 'enabled' in value and type(value['enabled']) is not bool
            or 'failure' in value and not isinstance(value['failure'],str)):
        raise ValueError('invalid Team state')
    return dict(value,tasks=TaskCollection(parse_task(task) for task in value['tasks']))


def parse_payload(kind,value):
    try:
        if kind=='team/mode':
            if not isinstance(value,dict) or set(value)!={'enabled'} or type(value['enabled']) is not bool:
                raise ValueError('invalid Team mode')
        elif (not isinstance(value,dict) or not safe_integer(value.get('version')) or not nonempty(value.get('teamId'))):
            raise ValueError('invalid Team event selector')
        return value
    except ValueError as cause:
        raise ValueError('persisted Agent Teams %s payload is invalid' % kind) from cause


def apply_task(state,task):
    index=next((i for i,other in enumerate(state['tasks']) if other['id']==task['id']),-1)
    prior=None if index<0 else state['tasks'][index]
    if prior is None and task['revision']!=1:
        raise ValueError('team task "%s" must begin at revision 1' % task['id'])
    if prior is not None and task['revision']!=prior['revision']+1:
        raise ValueError('team task "%s" revision is not contiguous' % task['id'])
    assert_task_graph_candidate(state['tasks'],task)
    number=state['nextTaskNumber'];match=TASK_NUMBER.fullmatch(task['id'])
    if match is not None:number=max(number,min(MAX_SAFE,int(match[1])+1))
    tasks=TaskCollection(state['tasks'])
    if index<0:tasks.append(task)
    else:tasks[index]=task
    return dict(state,enabled=state.get('enabled',True),tasks=tasks,nextTaskNumber=number)


def apply(state,event):
    try:
        if event['type']=='team/mode':
            if event['seq']<state['inheritedEventCount']:return state
            return dict(state,**parse_payload(event['type'],event['data']))
        if 'failure' in state or event['type']!='team/task':return state
        selector=parse_payload(event['type'],event['data'])
        if selector['teamId']!=state['id']:return state
        if selector['version']!=2:
            raise ValueError('unsupported Agent Teams event version %s' % selector['version'])
        try:
            if set(selector)!={'version','teamId','task'}:raise ValueError('invalid task event')
            task=parse_task(selector['task'])
        except (ValueError,KeyError) as cause:
            raise ValueError('persisted Agent Teams team/task payload is invalid') from cause
        return apply_task(state,task)
    except Exception as error:
        return dict(state,failure=state.get('failure',str(error)))


_views={}


def build_view(state):
    return dict(enabled=state.get('enabled') is True,
                tasks=[project_task_view(state,task) for task in state['tasks'] if task['status']!='deleted'],
                **(dict(failure=state['failure']) if 'failure' in state else {}))


def team_projection_view(state):
    if 'failure' in state:return build_view(state)
    tasks=state['tasks'];key=id(tasks);cached=_views.get(key)
    if cached is not None and cached[0]() is tasks and cached[1]['enabled']==(state.get('enabled') is True):
        return cached[1]
    view=build_view(state)
    def remove(reference):
        if key in _views and _views[key][0] is reference:_views.pop(key)
    try:_views[key]=(weakref.ref(tasks,remove),view)
    except TypeError:pass
    return view


def parse_view(value):
    if (not isinstance(value,dict) or set(value)-{'enabled','tasks','failure'} or type(value.get('enabled')) is not bool
            or not isinstance(value.get('tasks'),list) or 'failure' in value and not isinstance(value['failure'],str)):
        raise ValueError('invalid Team view')
    for task in value['tasks']:
        if (not isinstance(task,dict) or set(task)-{'id','revision','subject','description','status','blockedBy','writeScopes','ownerId','ownerName','ready','writeScopeWarnings'}
                or type(task.get('ready')) is not bool or not isinstance(task.get('writeScopeWarnings'),list)
                or not all(isinstance(item,str) for item in task['writeScopeWarnings'])):
            raise ValueError('invalid Team task view')
        parse_task({key:item for key,item in task.items() if key not in ('ready','writeScopeWarnings')})
    return value


TEAM=dict(key='agentTeam',stateVersion=7,stateSchema=parse_state,
          init=lambda header,cut:empty_team_state(header['id'],cut),apply=apply,
          wire=dict(viewSchema=parse_view,view=team_projection_view))
teamProjectionDefinition=TEAM
