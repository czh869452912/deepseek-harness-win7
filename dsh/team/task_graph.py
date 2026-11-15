"""Complete Team task DAG validation and detached advisory views."""


class TeamTaskGraphError(RuntimeError):
    def __init__(self,message,violation):
        super().__init__(message)
        self.name,self.message,self.violation='TeamTaskGraphError',message,violation


def assert_task_graph_candidate(current,candidate):
    tasks={task['id']:task for task in current}
    tasks[candidate['id']]=candidate
    for task in tasks.values():
        if task['status']=='deleted':continue
        seen=set()
        for blocker in task['blockedBy']:
            if blocker==task['id']:
                raise TeamTaskGraphError('team task "%s" cannot block itself' % task['id'],'cycle')
            if blocker in seen:
                raise TeamTaskGraphError('team task "%s" repeats blocker "%s"' % (task['id'],blocker),'duplicate')
            if blocker not in tasks or tasks[blocker]['status']=='deleted':
                raise TeamTaskGraphError('blocker task "%s" for "%s" is missing or deleted' % (blocker,task['id']),'missing')
            seen.add(blocker)
    visiting,visited=set(),set()
    for identity in tasks:
        stack=[(identity,False)]
        while stack:
            identity,leave=stack.pop()
            if leave:
                visiting.remove(identity);visited.add(identity);continue
            if identity in visiting:
                raise TeamTaskGraphError('task dependency cycle includes "%s"' % identity,'cycle')
            if identity in visited or identity not in tasks or tasks[identity]['status']=='deleted':continue
            visiting.add(identity);stack.append((identity,True))
            stack.extend((blocker,False) for blocker in reversed(tasks[identity]['blockedBy']))


def task_ready(state,task):
    return all(any(other['id']==identity and other['status']=='completed' for other in state['tasks'])
               for identity in task['blockedBy'])


def scopes_overlap(left,right):
    return left==right or left.startswith(right+'/') or right.startswith(left+'/')


def project_task_view(state,task):
    warnings=[]
    for other in state['tasks']:
        if other['id']==task['id'] or other['status']!='in_progress':continue
        if any(scopes_overlap(left,right) for left in task['writeScopes'] for right in other['writeScopes']):
            warning='write scopes overlap with '+other['id']
            if warning not in warnings:warnings.append(warning)
    return dict(task,blockedBy=list(task['blockedBy']),writeScopes=list(task['writeScopes']),
                ready=task['status']=='pending' and task_ready(state,task),writeScopeWarnings=warnings)
