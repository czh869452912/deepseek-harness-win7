"""Conditional four-tool Team task surface, using pinned upstream schemas."""
import copy
import json
from pathlib import Path
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.subagent.errors import SubagentError
from dsh.team.projection import safe_integer

DEFINITIONS=json.loads(Path(__file__).with_name('tool_definitions.json').read_text(encoding='utf-8'))


def with_owner_name(task):
    result={key:value for key,value in task.items() if key not in ('ownerId','ownerName')}
    if 'ownerId' in task:result['owner']=task.get('ownerName',task['ownerId'])
    return result


class TeamToolsPlugin(Plugin):
    id='tool-agent-team'
    inject=['agentTeams','subagents','tools','systemPrompt']
    Config=Schema.object({})

    def apply(self,ctx):
        for key in ('interrupt','freshProvider','forkProvider'):
            if key in self.config:
                raise RuntimeError('tool-agent-team: %s is no longer supported; create teammates with a subagent tool' % key)
        def enabled(agent):
            if agent is None:return False
            try:return ctx.get('agentTeams').isEnabled(agent)
            except SubagentError as error:
                if error.code!='UNAUTHORIZED':raise
                return False
        prompt=ctx.get('systemPrompt')
        prompt.section(dict(name='team:policy',order=prompt.getSectionOrder('TEAM_POLICY'),
            text=lambda context:DEFINITIONS['policy'] if enabled(context.get('agent')) else ''))
        for metadata in DEFINITIONS['tools']:
            name=metadata['name']
            async def execute(args,execution,name=name):
                caller=execution.agent
                if name=='team_task_list':
                    cursor=0 if args.get('cursor') is None else args['cursor']
                    limit=50 if args.get('limit') is None else args['limit']
                    if not safe_integer(cursor):raise RuntimeError('cursor must be a non-negative safe integer')
                    if not safe_integer(limit,1) or limit>100:raise RuntimeError('limit must be an integer from 1 through 100')
                if caller is None:raise RuntimeError(name+' requires a calling Agent')
                team=ctx.get('agentTeams');subagents=ctx.get('subagents')
                if name=='team_task_create':
                    request=dict(subject=args['subject'],description=args['description'])
                    for key,target in (('blocked_by','blockedBy'),('write_scopes','writeScopes')):
                        if key in args:request[target]=args[key]
                    return with_owner_name(await team.createTask(caller,request,execution.signal))
                if name=='team_task_get':return with_owner_name(team.getTask(caller,args['task_id']))
                if name=='team_task_update':
                    request=dict(taskId=args['task_id'],expectedRevision=args['expected_revision'],action=args['action'])
                    for key,target in (('subject','subject'),('description','description'),('blocked_by','blockedBy'),('write_scopes','writeScopes')):
                        if key in args:request[target]=args[key]
                    if 'owner' in args:request['owner']=await subagents.resolveName(caller,args['owner'],execution.signal)
                    return with_owner_name(await team.updateTask(caller,request,execution.signal))
                if 'owner' in args and 'unowned' in args:raise RuntimeError('owner and unowned filters cannot be combined')
                owner=await subagents.resolveName(caller,args['owner'],execution.signal) if 'owner' in args else None
                filtered=[task for task in team.listTasks(caller)
                    if ('status' not in args or task['status']==args['status'])
                    and ('owner' not in args or task.get('ownerId')==owner)
                    and ('unowned' not in args or ('ownerId' not in task)==args['unowned'])
                    and ('ready' not in args or task['ready']==args['ready'])]
                result=dict(tasks=[with_owner_name(task) for task in filtered[int(cursor):int(cursor+limit)]])
                if cursor+limit<len(filtered):result['nextCursor']=cursor+limit
                return result
            definition=dict(name=name,description=metadata['description'],parameters=copy.deepcopy(metadata['parameters']),execute=execute,
                output=dict(schema=copy.deepcopy(metadata['outputSchema']),render=lambda args,value:[dict(type='text',text=json.dumps(value,ensure_ascii=False,separators=(',',':')))]))
            if metadata['concurrencySafe']:definition['isConcurrencySafe']=lambda *_:True
            ctx.get('tools').register(definition,dict(when=lambda context:enabled(context.get('agent'))))
