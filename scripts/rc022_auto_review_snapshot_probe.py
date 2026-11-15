"""Review snapshot contracts against instrumented, unmodified Source helpers."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    schema = dict(name='probe', description='actual tool', parameters={'type': 'object'})
    def event(kind, **data):
        return dict(type=kind, data=data)
    def user(text, source=None, content=None):
        return event('user/message', source=source or dict(kind='user'), content=content or [dict(type='text', text=text)])
    def block(name='probe', id='call', arguments='{}'):
        return dict(type='tool-call', id=id, name=name, arguments=arguments)
    def base(name):
        return dict(name=name, header=dict(config=dict(provider='review', model='latest'), tools=[copy.deepcopy(schema)]),
                    meta=dict(origin='cli'), own=0, events=[user('Do the task'), event('step/start', turn=1, step=1),
                        event('assistant/message', turn=1, step=1, message=dict(content=[dict(type='reasoning', text='private'), block()])),
                        event('tool/call', turn=1, step=1, callId='call', name='probe', arguments='{}')],
                    execution=dict(name='probe', arguments={}, rootCallId='call', callId='call'))
    rows=[]
    def add(name, mutate=None):
        case=base(name)
        if mutate:mutate(case)
        rows.append(case)
        return case
    add('native')
    for key in ('provider', 'model'):
        add('empty-'+key, lambda c,k=key:c['header']['config'].update({k:''}))
    add('missing-header', lambda c:c.update(header=None))
    add('no-open-step', lambda c:c['events'].append(event('step/end', turn=1, step=1)))
    add('no-open-turn', lambda c:c['events'].append(event('turn/end', turn=1)))
    add('missing-surface', lambda c:c.update(hide=[2]))
    add('missing-root-log', lambda c:c['events'].pop())
    add('duplicate-root-log', lambda c:c['events'].append(copy.deepcopy(c['events'][-1])))
    add('duplicate-surface-root', lambda c:c['events'][2]['data']['message']['content'].append(block()))
    add('wrong-name', lambda c:c['execution'].update(name='other'))
    add('wrong-arguments', lambda c:c['execution'].update(arguments=dict(other=True)))
    add('visible-log-mismatch', lambda c:c['events'][2]['data']['message']['content'][-1].update(name='other'))
    for what in ('missing', 'duplicate', 'bad-description', 'bad-parameters', 'nonarray'):
        def mutate(c,what=what):
            if what=='missing':c['header'].pop('tools')
            elif what=='duplicate':c['header']['tools'] *= 2
            elif what=='bad-description':c['header']['tools'][0]['description']=None
            elif what=='bad-parameters':c['header']['tools'][0]['parameters']=[]
            else:c['header']['tools']={}
        add('schema-'+what,mutate)
    for raw, arguments in [('',{}),('not json','not json'),('null',None),('[1,true]',[1,True]),('{"b":2,"a":1}',dict(b=2,a=1)),('{"b":2,"a":1}',dict(a=1,b=2)),('{"2":2,"1":1}',{'1':1,'2':2}),('{"n":9007199254740993}',dict(n=9007199254740992))]:
        def mutate(c,raw=raw,arguments=arguments):
            c['events'][2]['data']['message']['content'][-1]['arguments']=raw
            c['events'][3]['data']['arguments']=raw
            c['execution']['arguments']=arguments
        add('raw-%d'%len(rows),mutate)
    for kind in ('user', 'agent-instructions', 'compact-checkpoint', 'tool', 'agent-message', 'unknown'):
        add('source-'+kind,lambda c,k=kind:c['events'].insert(0,user('visible',dict(kind=k),[dict(type='text',text='instruction'),dict(type='image',attachment=dict(attachmentId='image'))])))
    c=add('mixed-authority');c['events'].insert(0,user('all',dict(kind='user'),[dict(type='text',text='instruction'),dict(type='image',attachment=dict(attachmentId='image'))]))
    c=add('child-own-prompt');c['meta']=dict(origin='subagent',parentSession='parent');c['events'].insert(0,event('subagent/descriptor'));c['own']=0
    c=add('child-unverified');c['meta']=dict(origin='subagent',parentSession='parent')
    c=add('child-browser');c['meta']=dict(origin='subagent',parentSession='parent');c['events'][0]['data']['source']['rpcId']='browser'
    c=add('child-inherited');c['meta']=dict(origin='subagent',parentSession='parent');c['events'][:0]=[event('subagent/descriptor'),user('ancestor model prompt'),user('ancestor user',dict(kind='user',rpcId='browser')),event('subagent/descriptor')];c['own']=3
    for sender in ('parent','stranger'):
        c=add('sender-'+sender);c['meta']=dict(origin='subagent',parentSession='parent');c['events'].insert(0,user('delegate',dict(kind='agent-message',senderSessionId=sender)))
    c=add('missing-earlier-log');c['events'][2]['data']['message']['content'].insert(0,block(id='earlier'))
    c=add('unstarted-later');c['events'][2]['data']['message']['content'].append(block(id='later'))
    c=add('started-gap');c['events'][2]['data']['message']['content'].extend([block(id='missing'),block(id='later')]);c['events'].append(event('tool/call',turn=1,step=1,callId='later',name='probe',arguments='{}'))
    c=add('shown-old-schema');c['events'][2]['data']['message']['content'].insert(0,block(id='old'));c['events'].insert(3,event('tool/call',turn=1,step=1,callId='old',name='probe',arguments='{}'));c['shown']={'native\0'+'1\0'+'1\0old':dict(kind='tool-schema',role='fact',mode='native',**schema)}
    c=add('reused-id-other-step');prefix=copy.deepcopy(c['events'][1:]);prefix[0]['data']['step']=0;prefix[1]['data']['step']=0;prefix[2]['data']['step']=0;c['events'][:0]=prefix+[event('step/end',turn=1,step=0)]
    ptc_cases=[]
    def ptc(name, mutate=None):
        c=base(name);c['events'][2]['data']['message']['content'][-1].update(name='run_code',arguments='{"code":"probe()"}');c['events'][3]['data'].update(name='run_code',arguments='{"code":"probe()"}');c['events'].append(event('tool/ptc-dispatch-start',rootCallId='call',parentCallId='call',subCallId='inner',name='probe',arguments={}));c['execution'].update(callId='inner',parent=dict(name='run_code'),schema=copy.deepcopy(schema))
        if mutate:mutate(c)
        ptc_cases.append(c)
        return c
    ptc('ptc-valid')
    ptc('ptc-no-start',lambda c:c['events'].pop())
    ptc('ptc-duplicate',lambda c:c['events'].append(copy.deepcopy(c['events'][-1])))
    ptc('ptc-no-owning-step',lambda c:c['events'].insert(4,event('step/end',turn=1,step=1)))
    for key,value in [('parentCallId','hidden'),('rootCallId','other'),('name','other'),('arguments',dict(other=True))]:
        ptc('ptc-wrong-'+key,lambda c,k=key,v=value:c['events'][-1]['data'].update({k:v}))
    ptc('ptc-no-schema',lambda c:c['execution'].pop('schema'))
    ptc('ptc-wrong-schema',lambda c:c['execution']['schema'].update(name='other'))
    ptc('ptc-incomplete-schema',lambda c:c['execution']['schema'].pop('parameters'))
    c=ptc('ptc-history');c['events'].insert(4,event('tool/ptc-dispatch-start',rootCallId='call',parentCallId='call',subCallId='previous',name='other',arguments={'n':1,'2':'two','1':'one'}))
    c=ptc('ptc-nested-parent');c['events'].insert(4,event('tool/ptc-dispatch-start',rootCallId='call',parentCallId='call',subCallId='parent-inner',name='outer',arguments={}));c['events'][-1]['data']['parentCallId']='parent-inner'
    c=add('json-numbers');c['header']['tools'][0]['parameters']={'10':1e21,'2':1e-7,'n':-0.0,'unicode':'\ud800'}
    rows += ptc_cases
    c=add('integral-number-step')
    for entry in c['events']:
        if entry['type'] in ('step/start','assistant/message','tool/call'):
            entry['data'].update(turn=1.0,step=1.0)
    add('absent-origin',lambda c:c.update(meta={}))
    for case in rows:
        for seq,entry in enumerate(case['events']):entry['seq']=seq
        case['nodes']=[e['seq'] for e in case['events'] if e['type'] in ('user/message','assistant/message') and e['seq'] not in case.get('hide',[])]
    return rows


async def observe():
    from dsh.interaction.auto_review_snapshot import snapshot_auto_review, review_messages
    rows=[]
    for original in corpus():
        case=copy.deepcopy(original)
        session=NS(header=case['meta'],surface=NS(nodes=case['nodes']),snapshotEvents=lambda:case['events'],requestHeader=lambda:case['header'],isOwnSeq=lambda seq:seq>=case['own'])
        try:
            snapshot=snapshot_auto_review(NS(session=session),case['execution'],'C:/current 🐱',case.get('shown',{}))
            result=dict(snapshot=snapshot,messages=review_messages(snapshot))
        except Exception as error:result=dict(error=str(error))
        rows.append(dict(name=case['name'],result=result))
    return json.loads(json.dumps(rows))


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_auto_review_snapshot.mts','Actual private snapshot and message rendering: native/PTC started prefixes, step-scoped identities, logged schema/action equality, inherited/creation/browser/parent instruction authority, checkpoint and media facts, full canonical JSON and immutable snapshot.',[Path(__file__).resolve(),ROOT/'dsh/interaction/auto_review_snapshot.py'],prepare=prepare)
