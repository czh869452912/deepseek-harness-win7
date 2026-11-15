"""Pair installed V4 catalog admission and durable image replay with fixed Source."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_session_admission_probe import cases as admission_cases


def image_cases():
    invalid = [None, {}, dict(targets=[]), dict(targets='bad'), dict(targets=[None])]
    target = dict(seq=0, imageIndexes=[0])
    for key, values in dict(seq=[-1, -0.0, True, 0.5, '0', 9007199254740992, 3.0],
            imageIndexes=[[], [-1], [-0.0], [True], [0.5], ['0'], [1, 0], [0, 0], [2.0]]).items():
        for value in values:
            invalid.append(dict(targets=[dict(target, **{key: value})]))
    invalid += [dict(targets=[dict(target, extra=True)]), dict(targets=[target], extra=True),
                dict(targets=[target, dict(seq=0.0, imageIndexes=[1])])]
    return invalid


def catalog_cases():
    rows=[]
    for case in admission_cases():
        for validation in ('current', 'transformed'):
            for recovery in ('strict', 'recoverable-tail'):
                rows.append(dict(name=case['name']+'-'+validation+'-'+recovery, header=dict(type='session', **case['header']),
                    events=case['events'], validation=validation, recovery=recovery))
    for version in range(8):
        header=dict(type='session', version=version, id='parent', createdAt=1, delegationDepth=0)
        header.update(dict(seedLength=0) if version<2 else dict(isSeeded=False))
        for children in (False, True):
            rows.append(dict(name='version-%s-children-%s'%(version,children), header=header,
                events=[], validation='current', recovery='strict', children=children))
    # The generated catalog must supply the interpreter even without a mounted plugin.
    message=dict(id='image', role='user', source=dict(kind='user'), content=[dict(type='image',attachment={})])
    rows.append(dict(name='catalog-image',header=dict(type='session',version=4,id='image',createdAt=1,isSeeded=False,delegationDepth=0),
        events=[dict(type='user/message',seq=0,time=1,data=message,surfaceOp='append'),
                dict(type='image/offload',seq=1,time=2,data=dict(targets=[dict(seq=0,imageIndexes=[0])]))],
        validation='current',recovery='strict'))
    lifecycle=[]
    def emit(kind, data, **metadata):
        lifecycle.append(dict(type=kind,seq=len(lifecycle),time=1,data=data,**metadata))
    emit('turn/start',dict(turn=1))
    emit('step/start',dict(turn=1,step=1))
    emit('system/message',dict(turn=1,step=1,message=dict(id='system',role='system',source=dict(kind='system-prompt'),content=[])),surfaceOp='append')
    emit('request/header',dict(reason='initial',header=dict(config=dict(provider='mock',model='mock'),tools=[dict(name='demo',description='',parameters={})])))
    emit('developer/message',dict(turn=1,step=1,headerSeq=3,message=dict(id='developer',role='developer',source=dict(kind='tool-registry'),content=[dict(type='tool-addition',toolName='demo')])),surfaceOp='append')
    emit('assistant/message',dict(turn=1,step=1,stream=[],message=dict(id='assistant',role='assistant',source=dict(kind='model',provider='mock',model='mock'),content=[dict(type='tool-call',id='call',name='demo',arguments='{}')])),surfaceOp='append')
    emit('tool/call',dict(turn=1,step=1,callId='call',name='demo',arguments='{}'))
    emit('tool/result',dict(turn=1,step=1,message=dict(id='tool',role='tool',source=dict(kind='tool',callId='call'),toolCallId='call',content=[dict(type='image',attachment={})])),surfaceOp='append')
    emit('image/offload',dict(targets=[dict(seq=7,imageIndexes=[0])]))
    emit('step/end',dict(turn=1,step=1));emit('turn/end',dict(turn=1))
    for mode in ('valid','invalid-surface','invalid-image'):
        events=copy.deepcopy(lifecycle)
        if mode=='invalid-surface':events[7].pop('surfaceOp')
        if mode=='invalid-image':events[8]['data']['targets'][0]['imageIndexes']=[1]
        rows.append(dict(name='lifecycle-'+mode,header=copy.deepcopy(rows[-1]['header']),events=events,validation='current',recovery='strict'))
    return rows


def prepare(output):
    path=output/'input.json'
    path.write_text(json.dumps(dict(images=image_cases(),catalog=catalog_cases())),encoding='utf-8')
    return [path]


def image_rows():
    from dsh.compaction.image_offload import imageOffloadProjection
    from dsh.core.session.current_session import CurrentSession
    from dsh.core.session.current_surface import foldSurface, deriveEventMessage
    from dsh.core.session.json import UNDEFINED
    def session(name='images', *args, **kwargs):
        return CurrentSession.create(name,*args,format_version=4,projections=[imageOffloadProjection],**kwargs)
    def content():
        return [dict(type='text',text='before'), dict(type='image',attachment={}),
                dict(type='image',attachment={}), dict(type='text',text='after')]
    def input(current):
        return current.append('user/message',dict(id='image',role='user',source=dict(kind='user'),content=content()),surface_op='append')
    def marked(current):
        return [block.get('offloaded') is True for message in current.deriveMessages() for block in message['content'] if block['type']=='image']
    def decision(indexes, seq=0):return dict(targets=[dict(seq=seq,imageIndexes=indexes)])
    rows=[]
    for index,data in enumerate(image_cases()):
        current=session();input(current);result=dict(name='invalid-%s'%index)
        for action in ('append','resume','fold'):
            try:
                if action=='append':current.append('image/offload',data)
                else:
                    events=[*current.snapshotEvents(),dict(type='image/offload',seq=1,time=1,data=data)]
                    if action=='resume':session('seed',events)
                    else:foldSurface(events,[imageOffloadProjection],4)
                result[action]='accepted'
            except Exception as error:result[action]=str(error)
        result.update(seq=current.seq,marked=marked(current),generation=current.surface.contentGeneration)
        current.append('image/offload',decision([1]));result['after']=marked(current);rows.append(result)
    current=session();source=input(current);before=current.deriveMessages()
    current.append('image/offload',decision([1]));after=current.deriveMessages()
    result=dict(name='identity',marked=marked(current),sameId=after[0]['id']==before[0]['id'],
        untouched=after[0]['content'][0] is before[0]['content'][0],
        original='offloaded' not in json.dumps(source),old='offloaded' not in json.dumps(before),
        projected=current.deriveEventMessage(source) is after[0],nodes=list(current.surface.nodes),
        position=current.surface.replaceGeneration,generation=current.surface.contentGeneration,
        decisionMessage=current.deriveEventMessage(current.snapshotEvents()[-1]))
    current.append('image/offload',decision([0]));result.update(final=marked(current),fresh=current.deriveMessages()[0] is not after[0]);rows.append(result)
    events=current.snapshotEvents();fold=foldSurface(events,[imageOffloadProjection],4)
    restored=CurrentSession.from_restore(current.id,events,current.header,0,'shared-frozen',format_version=4,projections=[imageOffloadProjection])
    child=session('child',events,dict(current.header.to_dict(),id='child',parentSession=current.id,isSeeded=True),len(events))
    input(child)
    rows.append(dict(name='replay',fold=deriveEventMessage(source,fold['projectedMessages'],4)['content'],
        restored=marked(restored),resumed=marked(session('resume',events)),child=marked(child),parent=marked(current)))
    for action in ('repeat','shadowed','assistant','tool','atomic'):
        current=session();source=input(current);result=dict(name=action)
        try:
            if action=='repeat':
                current.append('image/offload',decision([0]));current.append('image/offload',decision([0]))
            elif action=='shadowed':
                current.append('user/message',dict(source['data'],content=[]),surface_op=dict(op='replace',startSeq=0,endSeq=0),source_event_seqs=[0])
                current.append('image/offload',decision([0]))
            elif action in ('assistant','tool'):
                message=dict(id=action,role=action,source=dict(kind='model',provider='mock',model='mock') if action=='assistant' else dict(kind='tool',callId='call'),content=content())
                if action=='tool':message['toolCallId']='call'
                data=dict(turn=1,step=1,message=message)
                if action=='assistant':data['stream']=[]
                event=current.append('assistant/message' if action=='assistant' else 'tool/result',data,surface_op='append')
                current.append('image/offload',decision([1],event['seq']))
            else:
                current.append([('image/offload',decision([0])),('image/offload',decision([0]))])
        except Exception as error:result['error']=str(error)
        result.update(seq=current.seq,marked=marked(current),generation=current.surface.contentGeneration);rows.append(result)
    return rows


def catalog_row(row):
    from dsh.session.format_catalog import candidateSessionFormatCatalog, createSessionFormatCatalogWithChildren
    catalog=createSessionFormatCatalogWithChildren([]) if row.get('children') else candidateSessionFormatCatalog
    result=dict(name=row['name'],classification=catalog.readHeader(copy.deepcopy(row['header'])))
    try:
        restore=catalog.createRestore(copy.deepcopy(row['header']),dict(validation=row['validation'],recovery=row['recovery']))
        for event in row['events']:restore.decodeRow(catalog.encodeCurrentEvent(copy.deepcopy(event)))
        result['artifact']=restore.finish()
    except Exception as error:result['error']=str(error)
    return result


async def native():
    return json.loads(json.dumps(dict(images=image_rows(),catalog=[catalog_row(row) for row in catalog_cases()])))


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_image_catalog.mts','V4 current catalog physical recovery and installed Session validation; pure image decisions at live append, batch, replay, fold and fork. Production selection remains V3.',
        [Path(__file__).resolve(),*[ROOT/path for path in ('dsh/compaction/image_offload.py','dsh/session/format_catalog/candidate.py','dsh/session/format_catalog/current.py','dsh/session/format_catalog/message_projections.py')]],prepare)
