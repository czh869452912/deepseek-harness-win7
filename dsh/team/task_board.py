"""Authorized revision-checked task mutations shared by one subagent tree."""
from dsh.team.errors import TeamError
from dsh.team.task_graph import assert_task_graph_candidate,TeamTaskGraphError,project_task_view,task_ready
from dsh.team.validation import required_text,write_scope

GRAPH_CODES=dict(missing='TEAM_TASK_NOT_FOUND',duplicate='TEAM_INVALID_ARGUMENT',cycle='TEAM_TASK_DEPENDENCY_CYCLE')


def without_owner(task):
    return {key:value for key,value in task.items() if key not in ('ownerId','ownerName')}


class TeamTaskBoard:
    def __init__(self,ctx,journal,max_tasks):
        self.ctx,self.journal,self.max_tasks=ctx,journal,max_tasks

    def state(self,root):
        state=self.journal.state(root)
        if state.get('enabled') is not True:
            raise TeamError('enable Agent Teams for this Session before using the task board','TEAM_DISABLED')
        return state

    def create(self,caller,root,request,signal=None):
        async def operation():
            if signal is not None:signal.throwIfAborted()
            state=self.state(root)
            if sum(task['status']!='deleted' for task in state['tasks'])>=self.max_tasks:
                raise TeamError('Team task limit %s reached' % self.max_tasks,'TEAM_TASK_LIMIT')
            identity='task-%s' % state['nextTaskNumber']
            if any(task['id']==identity for task in state['tasks']):
                raise TeamError('Team task id space exhausted','TEAM_TASK_LIMIT')
            task=dict(id=identity,revision=1,subject=required_text(request['subject'],'subject',200),
                description=required_text(request['description'],'description',16384),status='pending',
                blockedBy=self.dependencies(request.get('blockedBy',[]),state),writeScopes=self.write_scopes(request.get('writeScopes',[])))
            self.assert_graph(state,task)
            self.ctx.get('subagents').rootOf(caller)
            await self.journal.append_and_flush(root,task)
            return project_task_view(state,task)
        return self.journal.transact(root.id,operation)

    def get(self,root,identity):
        state=self.state(root)
        task=next((task for task in state['tasks'] if task['id']==identity),None)
        if task is None:raise TeamError('team task "%s" not found' % identity,'TEAM_TASK_NOT_FOUND')
        return project_task_view(state,task)

    def list(self,root):
        state=self.state(root)
        return [project_task_view(state,task) for task in state['tasks'] if task['status']!='deleted']

    def update(self,caller,root,request,signal=None):
        async def operation():
            if signal is not None:signal.throwIfAborted()
            state=self.state(root);identity=request['taskId']
            current=next((task for task in state['tasks'] if task['id']==identity),None)
            if current is None:raise TeamError('team task "%s" not found' % identity,'TEAM_TASK_NOT_FOUND')
            if current['revision']!=request['expectedRevision']:
                raise TeamError('stale team task "%s" revision %s; current revision is %s' %
                    (identity,request['expectedRevision'],current['revision']),'TEAM_TASK_STALE_REVISION')
            if current['status']=='deleted':raise TeamError('team task "%s" is deleted' % identity,'TEAM_TASK_DELETED')
            lead=caller is root;owner=current.get('ownerId')==caller.id
            def authorize_owner():
                if not lead and not owner:raise TeamError('task mutation requires its owner or Team Lead','TEAM_TASK_UNAUTHORIZED')
            action=request['action'];next_task=dict(current)
            if action=='claim':
                if 'ownerId' in current and not owner:
                    raise TeamError('team task "%s" is owned by another member' % identity,'TEAM_TASK_ALREADY_CLAIMED')
                if current['status']!='pending' or not task_ready(state,current):
                    raise TeamError('team task "%s" is not ready to claim' % identity,'TEAM_TASK_BLOCKED')
                name=self.ctx.get('subagents').namesOf(caller)['self']
                next_task=dict(without_owner(current),status='in_progress',ownerId=caller.id)
                if name!=caller.id:next_task['ownerName']=name
            elif action=='release':
                authorize_owner()
                if current['status']!='in_progress':
                    raise TeamError('only an in-progress task can be released','TEAM_TASK_INVALID_TRANSITION')
                next_task=without_owner(dict(current,status='pending'))
            elif action=='edit':
                authorize_owner()
                if not any(key in request for key in ('subject','description','writeScopes')):
                    raise TeamError('task edit requires subject, description, or write_scopes','TEAM_INVALID_ARGUMENT')
                for key,limit in (('subject',200),('description',16384)):
                    if key in request:next_task[key]=required_text(request[key],key,limit)
                if 'writeScopes' in request:next_task['writeScopes']=self.write_scopes(request['writeScopes'])
            elif action=='set_dependencies':
                authorize_owner()
                if 'blockedBy' not in request:raise TeamError('set_dependencies requires blocked_by','TEAM_INVALID_ARGUMENT')
                next_task['blockedBy']=self.dependencies(request['blockedBy'],state,identity)
            elif action in ('complete','reopen'):
                authorize_owner()
                required='in_progress' if action=='complete' else 'completed'
                if current['status']!=required:
                    raise TeamError('only %s task can %s' % ('an in-progress' if action=='complete' else 'a completed',action),'TEAM_TASK_INVALID_TRANSITION')
                next_task['status']='completed' if action=='complete' else 'pending'
                if action=='reopen':next_task=without_owner(next_task)
            elif action=='reassign':
                if not lead:raise TeamError('only the Team Lead can reassign tasks','TEAM_LEAD_REQUIRED')
                if current['status'] not in ('pending','in_progress'):
                    raise TeamError('only a pending or in-progress task can be reassigned','TEAM_TASK_INVALID_TRANSITION')
                next_task=dict(without_owner(current),status='pending')
                if 'owner' in request:
                    if not task_ready(state,current):raise TeamError('team task "%s" is blocked' % identity,'TEAM_TASK_BLOCKED')
                    next_task.update(status='in_progress',**await self.resolve_assignee(root,request['owner'],signal))
            elif action=='delete':
                authorize_owner()
                dependent=next((task for task in state['tasks'] if task['status']!='deleted'
                    and task['id']!=identity and identity in task['blockedBy']),None)
                if dependent is not None:
                    raise TeamError('team task "%s" still blocks "%s"' % (identity,dependent['id']),'TEAM_TASK_HAS_DEPENDENTS')
                next_task['status']='deleted'
            else:raise TeamError('unsupported task action '+str(action),'TEAM_INVALID_ARGUMENT')
            task=dict(next_task,revision=current['revision']+1)
            self.assert_graph(state,task)
            if signal is not None:signal.throwIfAborted()
            self.ctx.get('subagents').rootOf(caller)
            await self.journal.append_and_flush(root,task)
            return project_task_view(state,task)
        return self.journal.transact(root.id,operation)

    async def resolve_assignee(self,root,target,signal):
        subagents=self.ctx.get('subagents')
        if target==root.id:return dict(ownerId=target,ownerName=subagents.namesOf(root)['self'])
        descendants=await subagents.listDescendants(root.id,signal)
        member=next((entry for entry in descendants if entry.get('kind')!='diagnostic' and entry.get('mode')=='continuable' and entry['id']==target),None)
        if member is not None:return dict(ownerId=target,**(dict(ownerName=member['path']) if 'path' in member else {}))
        raise TeamError('agent "%s" is not a continuable descendant of this task board\'s root' % target,'TEAM_MEMBER_NOT_FOUND')

    @staticmethod
    def dependencies(values,state,self_id=None):
        seen=set();result=[]
        for identity in values:
            if identity==self_id:raise TeamError('a team task cannot block itself','TEAM_TASK_DEPENDENCY_CYCLE')
            if identity in seen:raise TeamError('duplicate blocker "%s"' % identity,'TEAM_INVALID_ARGUMENT')
            if not any(task['id']==identity and task['status']!='deleted' for task in state['tasks']):
                raise TeamError('blocker task "%s" not found' % identity,'TEAM_TASK_NOT_FOUND')
            seen.add(identity);result.append(identity)
        return result

    @staticmethod
    def write_scopes(values):
        return list(dict.fromkeys(write_scope(value) for value in values))

    @staticmethod
    def assert_graph(state,candidate):
        try:assert_task_graph_candidate(state['tasks'],candidate)
        except TeamTaskGraphError as cause:
            raise TeamError(cause.message,GRAPH_CODES[cause.violation],cause=cause) from cause
