"""Pair durable Team transitions, graph validation and normalized inputs."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def task(**overrides):
    return dict(dict(id='task-1',revision=1,subject='subject',description='description',status='pending',blockedBy=[],writeScopes=[]),**overrides)


def cases():
    rows=[]
    def project(name,events,cut=0):rows.append(dict(kind='project',name=name,events=events,cut=cut))
    def event(value,team='root',version=2):return dict(type='team/task',data=dict(version=version,teamId=team,task=value))
    mode=lambda value:dict(type='team/mode',data=dict(enabled=value))
    project('empty',[])
    project('task-enables',[event(task())])
    project('explicit-disabled',[mode(False),event(task())])
    project('toggle-preserves-tasks',[event(task()),mode(False),mode(True)])
    project('inherited-mode',[mode(True),event(task(),team='ancestor'),mode(False),event(task())],2)
    project('retired-records',[dict(type=kind,data=None) for kind in ('team/member','team/message/queued','team/message/delivered')]+[event(task())])
    project('foreign-malformed-task',[event(None,team='foreign',version=90),event(task())])
    for name,events in (
            ('invalid-selector',[dict(type='team/task',data={})]),
            ('unsupported-version',[event(task(),version=3)]),
            ('strict-task-event',[dict(type='team/task',data=dict(version=2,teamId='root',task=task(),extra=True))]),
            ('invalid-task',[event(task(revision=0))]),
            ('initial-revision',[event(task(revision=2))]),
            ('noncontiguous',[event(task()),event(task(revision=3))]),
            ('duplicate-blocker',[event(task()),event(task(id='task-2',blockedBy=['task-1','task-1']))]),
            ('missing-blocker',[event(task(blockedBy=['missing']))]),
            ('self-cycle',[event(task(blockedBy=['task-1']))]),
            ('transitive-cycle',[event(task()),event(task(id='task-2',blockedBy=['task-1'])),event(task(revision=2,blockedBy=['task-2']))]),
            ('delete-blocker',[event(task()),event(task(id='task-2',blockedBy=['task-1'])),event(task(revision=2,status='deleted'))]),
            ('mode-after-failure',[event(task()),event(task(revision=4)),mode(False),event(task(id='task-2')),mode(True)]),
            ('mode-failure-sticky',[dict(type='team/mode',data=dict(enabled=1)),mode(True)]),
            ('malformed-inherited-mode',[dict(type='team/mode',data=None)])):
        project(name,events,1 if name=='malformed-inherited-mode' else 0)
    project('scopes-readiness',[event(task(status='in_progress',ownerId='root',ownerName='lead',writeScopes=['src'])),
        event(task(id='task-2',blockedBy=['task-1'],writeScopes=['src/a','src-extra'])),
        event(task(revision=2,status='completed',writeScopes=['src']))])
    project('tombstone',[event(task()),event(task(revision=2,status='deleted'))])
    project('safe-id-exhausted',[event(task(id='task-9007199254740991'))])
    project('unsafe-id',[event(task(id='task-9007199254740992'))])
    project('owner-without-id',[event(task(ownerName='worker'))])
    project('legacy-owner',[event(task(ownerId='child'))])
    for value in ('src','./src/','src\\dir\\','src//dir','../src','/root','C:\\src','.','./','src/./x','src/../x','src///',' src ','././src','src/a','src-extra',''):
        rows.append(dict(kind='scope',value=value))
    for value,limit in (('\ufeff hello \u00a0',5),('',3),(' \n ',5),('😀',1),('😀',2),('a\u0085',1),('\u0085',1),(' hello ',4)):
        rows.append(dict(kind='text',value=value,limit=limit))
    base=dict(inheritedEventCount=0,id='root',tasks=[task()],nextTaskNumber=2)
    for name,change in (('valid',{}),('old-owner',dict(tasks=[task(ownerId='child')])),('bad-enabled',dict(enabled=1)),
            ('bad-cut',dict(inheritedEventCount=-1)),('bad-next',dict(nextTaskNumber=9007199254740992)),
            ('extra-state',dict(extra=True)),('extra-task',dict(tasks=[task(extra=True)])),
            ('unsafe-revision',dict(tasks=[task(revision=9007199254740992)])),('bad-owner',dict(tasks=[task(ownerId='')]))):
        rows.append(dict(kind='checkpoint',name=name,value=dict(base,**change)))
    return rows


async def observe():
    from dsh.team.projection import TEAM,empty_team_state,apply,team_projection_view,parse_state
    from dsh.team.validation import write_scope,required_text
    rows=[]
    for case in cases():
        row=dict(kind=case['kind'],name=case.get('name',case.get('value')))
        try:
            if case['kind']=='project':
                state=empty_team_state('root',case['cut']);steps=[]
                for seq,data in enumerate(case['events']):
                    prior=state;state=apply(state,dict(data,seq=seq,time=seq))
                    view=team_projection_view(state)
                    steps.append(dict(state=state,view=view,sameState=state is prior,sameTasks=state['tasks'] is prior['tasks'],
                                      sameView=view is team_projection_view(state)))
                row.update(state=state,view=team_projection_view(state),steps=steps)
            elif case['kind']=='scope':row['value']=write_scope(case['value'])
            elif case['kind']=='text':row['value']=required_text(case['value'],'subject',case['limit'])
            else:
                row['accepted']=True
                try:parse_state(copy.deepcopy(case['value']))
                except Exception:row['accepted']=False
        except Exception as error:row['error']=dict(code=error.code,message=error.message)
        rows.append(row)
    return json.loads(json.dumps(rows))


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_team_projection.mts','Team v7 durable projection: revision/strict schemas, first failure preservation and mode continuation, inherited and retired records, DAG/readiness/scopes, weak client view reuse and checkpoint boundaries.',
        [Path(__file__).resolve(),*[ROOT/'dsh/team'/name for name in ('projection.py','task_graph.py','validation.py','errors.py')]],prepare=prepare)
