"""Compare explicit V4 Session admission and message interpretation ownership."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

OUTPUT = None


def cases():
    rows = []
    header = dict(version=4, id='session', createdAt=1, isSeeded=False, delegationDepth=0)
    def add(name, events, **options):
        rows.append(dict(name=name, header=copy.deepcopy(header), events=copy.deepcopy(events), **options))
    def event(kind, message, **data):
        payload = message if kind == 'user/message' else dict(message=message, **data)
        return dict(type=kind, seq=0, time=1, surfaceOp='append', data=payload)
    messages = {
        'user/message':dict(id='user',role='user',source=dict(kind='user'),content=[]),
        'system/message':dict(id='system',role='system',source=dict(kind='system-prompt'),content=[]),
        'developer/message':dict(id='developer',role='developer',source=dict(kind='plugin',plugin='demo'),content=[]),
        'assistant/message':dict(id='assistant',role='assistant',source=dict(kind='model',provider='mock',model='mock'),content=[]),
        'tool/result':dict(id='tool',role='tool',source=dict(kind='tool',callId='call'),toolCallId='call',content=[]),
    }
    for kind, message in messages.items():
        extra = dict(turn=1,step=1,stream=[]) if kind == 'assistant/message' else {}
        base = event(kind, message, **extra)
        add(kind+'-valid', [base])
        for key, values in {
            'role':['user','system','developer','assistant','tool',None],
            'id':['',None,0], 'source':[{},None,dict(kind=''),dict(kind='plugin'),dict(kind='system-prompt')],
            'content':[None,{},[dict(type='text',text='text')],[dict(type='tool-addition',toolName='tool')]],
        }.items():
            for value in values:
                changed=copy.deepcopy(base)
                target=changed['data'] if kind == 'user/message' else changed['data']['message']
                target[key]=value
                add('%s-%s-%s' % (kind,key,len(rows)), [changed])
    tool = event('tool/result', messages['tool/result'])
    for is_error in ('absent',True,False,None):
        for error in ('absent',None,dict(kind='ABORTED')):
            item=copy.deepcopy(tool)
            if is_error!='absent':item['data']['message']['isError']=is_error
            if error!='absent':item['data']['error']=error
            add('tool-error-%s'%len(rows),[item])
    for changed in ({}, dict(id='changed'), dict(isError=True), dict(toolCallId='other')):
        replacement=copy.deepcopy(tool)
        replacement.update(seq=1,surfaceOp=dict(op='replace',startSeq=0,endSeq=0),sourceEventSeqs=[0])
        replacement['data']['message'].update(content=[dict(type='text',text='replacement')],**changed)
        add('tool-rewrite-%s'%len(rows),[tool,replacement])
    request=dict(type='request/header',seq=0,time=1,data=dict(reason='initial',header=dict(
        config=dict(provider='mock',model='mock'),tools=[dict(name='demo',description='',parameters={})])))
    for kind in ('tool-addition','tool-removal'):
        for name in ('demo','missing','',None):
            for reference in ('absent',0,1,-1):
                developer=event('developer/message',dict(messages['developer/message'],content=[dict(type=kind,toolName=name)]))
                developer['seq']=1
                if reference!='absent':developer['data']['headerSeq']=reference
                add('developer-reference-%s'%len(rows),[request,developer])
    developer=event('developer/message',dict(messages['developer/message'],content=[dict(type='tool-addition',toolName='demo')]),headerSeq=0)
    developer['seq']=1
    for change in (dict(description=None),dict(parameters=[]),dict(deferLoading=False),dict(deferLoading=True)):
        changed=copy.deepcopy(request);changed['data']['header']['tools'][0].update(change)
        add('developer-definition-%s'%len(rows),[changed,developer])
    for definitions in ([],[dict(name='demo',description='',parameters={})]*2):
        changed=copy.deepcopy(request);changed['data']['header']['tools']=definitions
        add('developer-duplicates-%s'%len(rows),[changed,developer])
    for mode in ('create','restore'):
        for cut, markers in ((0,[0]),(0,[0,1]),(1,[0]),(1,[1]),(1,[])):
            events=[dict(type='session/end-seed',seq=index,time=1,data=dict(inherited=True) if index in markers else {}) for index in range(2)]
            add('seed-%s-%s-%s'%(mode,cut,markers),events,mode=mode,cut=cut)
            rows[-1]['header']['isSeeded']=True
    add('missing-projection',[dict(type='image/offload',seq=0,time=1,data={})])
    return rows


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8')
    return [path]


def native_row(row):
    from dsh.core.session.current_session import CurrentSession
    result=dict(name=row['name'])
    try:
        args=['session',copy.deepcopy(row['events']),copy.deepcopy(row['header']),row.get('cut',0)]
        if row.get('mode')=='create':
            session=CurrentSession.create(*args,format_version=4)
        else:
            session=CurrentSession.from_restore(*args,format_version=4)
        result.update(seq=session.seq,nodes=list(session.surface.nodes),messages=session.deriveMessages(),
            firstLiveSeq=session.firstLiveSeq,firstLifecycleSeq=session.firstLifecycleSeq,
            inheritedEventCount=session.inheritedEventCount,types=[event['type'] for event in session.snapshotEvents()])
    except Exception as error:
        result['error']=str(error)
    return result


def projection_rows():
    from dsh.core.session.current_session import CurrentSession
    from dsh.core.session.current_surface import CurrentSurfaceManager
    rows=[]
    for action in ('read','remove','replace','remove-pending','unused'):
        def project(event, context):
            original=context.events[0]['data']
            return {0:dict(original,content=[dict(type='text',text='projected')])}
        definition=dict(type='image/offload',project=project)
        definitions=[definition]
        session=CurrentSession.create('projection',format_version=4,projections=definitions)
        session.append_user_message('original')
        result=dict(name='projection-'+action)
        if action!='unused':session.append('image/offload',{})
        if action not in ('remove-pending','unused'):
            result['before']=[message['content'] for message in session.deriveMessages()]
        if action in ('remove','remove-pending','unused'):definitions.clear()
        elif action=='replace':definitions[0]=dict(definition)
        try:
            result.update(messages=[message['content'] for message in session.deriveMessages()],
                          generation=session.surface.contentGeneration,position=session.surface.replaceGeneration)
        except Exception as error:result['error']=str(error)
        rows.append(result)
    # A plan that was never committed does not retain a definition.
    definitions=[dict(type='image/offload',project=lambda event,context:{})]
    manager=CurrentSurfaceManager([],format_version=4,projections=definitions)
    manager.validateNext(dict(type='image/offload',seq=0,time=1,data={}))
    definitions.clear();rows.append(dict(name='projection-uncommitted',nodes=manager.nodes))
    return rows


async def native():
    # JSON transport materializes Python immutable containers and numeric brands.
    return json.loads(json.dumps([native_row(row) for row in cases()]+projection_rows()))


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_session_admission.mts','Explicit V4 Session constructor, developer tool header references, tool/system roles and required message interpreter identity. Production Session selection remains V3.',
        [Path(__file__).resolve(),*[ROOT/'dsh/core/session'/name for name in ('current.py','current_session.py','current_surface.py','current_vocabulary.py')],
         ROOT/'reference/packages/core/session/src/index.ts',
         ROOT/'reference/packages/core/session/src/surface.ts'],prepare)
