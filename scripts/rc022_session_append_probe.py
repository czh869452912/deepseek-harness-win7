"""Pair atomic batch commit, dispatch and store publication guards."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def message(text):
    return dict(id=text,role='user',source=dict(kind='user'),content=[dict(type='text',text=text)])


def cases():
    user=['user/message',message('first'),dict(surfaceOp='append')]
    simple=[['turn/start',dict(turn=1)],user]
    replacement=['user/message',message('replacement'),dict(surfaceOp=dict(op='replace',startSeq=0,endSeq=0),sourceEventSeqs=[0])]
    header=['request/header',dict(reason='initial',header=dict(config=dict(provider='mock',model='mock'),tools=[dict(name='demo',description='',parameters={})]))]
    developer=['developer/message',dict(headerSeq=0,message=dict(id='dev',role='developer',source=dict(kind='plugin',plugin='demo'),content=[dict(type='tool-addition',toolName='demo')])),dict(surfaceOp='append')]
    return [dict(name=name,inputs=copy.deepcopy(items)) for name,items in (
        ('simple',simple),('replace',[user,replacement]),('invalid-surface',[simple[0],user[:2]]),
        ('project',[user,['test/project',dict(seq=0,text='projected')]]),
        ('project-reject',[user,['test/project',dict(seq=0,text='reject')]]),
        ('developer',[header,developer]),('developer-invalid',[header,dict_to_invalid(developer)]),
        ('empty',[]),('empty-member',[simple[0],None,user]),
        ('dispatch-veto',simple),('reentrant',simple),('detach',simple),('listener-change',simple))]


def dict_to_invalid(developer):
    value=copy.deepcopy(developer);value[1]['headerSeq']=1
    return value


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.core.session.json import UNDEFINED
    results=[]
    class Store(Plugin):
        def apply(self,owner):CurrentSessionStore(owner,4)
    for row in cases():
        ctx=Context();name=row['name'];result=dict(name=name,observed=[],extra=[],reentry=[])
        try:
            await ctx.plugin(Store);store=ctx.get('sessions')
            def project(event,context):
                if event['data']['text']=='reject':raise ValueError('rejected decision')
                seq=event['data']['seq'];original=context.events[int(seq-context.baseSeq)]['data']
                return {seq:dict(original,content=[dict(type='text',text=event['data']['text'])])}
            store.registerMessageProjection(dict(type='test/project',project=project))
            session=store.prepare('batch');detach=store.enter(session);store.announce(session)
            def callback(current,event):
                result['observed'].append(dict(seq=event['seq'],length=current.seq,nodes=list(current.surface.nodes),
                    messages=[value['content'] for value in current.deriveMessages()],member=current.currentBatchPublication is event,
                    live=store.get(current.id) is current))
                if name=='reentrant':
                    try:current.append('turn/end',{})
                    except Exception as error:result['reentry'].append(str(error))
                if name=='detach':detach()
                if name=='listener-change' and event['seq']==0:
                    ctx.on('session/event',lambda current,member:result['extra'].append(member['seq']))
            ctx.on('session/event',callback)
            def dispatch(mode,event,args,receiver=None):
                if name=='dispatch-veto' and event=='session/event' and args[1]['seq']==1:
                    raise ValueError('veto final event')
            ctx.on('internal/dispatch',dispatch)
            try:
                events=session.append(copy.deepcopy(row['inputs']))
                result['returned']=[event['seq'] for event in events]
            except Exception as error:result['error']=str(error)
            result.update(seq=session.seq,nodes=list(session.surface.nodes),messages=[value['content'] for value in session.deriveMessages()],
                          publicationCleared=session.currentBatchPublication is UNDEFINED,live=store.get(session.id) is session)
            if name=='detach':
                try:session.append([])
                except Exception as error:result['afterDetach']=str(error)
            if name=='listener-change':
                session.append('turn/end',{})
            results.append(result)
        finally:await ctx.fiber.dispose()
    for action in ('normal','failed','detach-created'):
        ctx=Context();result=dict(name='membership-'+action,stages=[])
        try:
            await ctx.plugin(Store);store=ctx.get('sessions');session=store.prepare('membership')
            def attempt():
                try:session.append([]);return 'value'
                except Exception as error:return str(error)
            result['stages'].append(attempt());detach=store.enter(session);result['stages'].append(attempt())
            def created(current):
                result['stages'].append(attempt())
                if action=='failed':raise ValueError('creation observer failed')
                if action=='detach-created':detach()
            stop=ctx.on('session/created',created)
            try:store.announce(session)
            except Exception as error:result['announcement']=str(error)
            result['stages'].append(attempt())
            if action=='failed':
                try:store.announce(session)
                except Exception as error:result['reannounce']=str(error)
            detach();result['stages'].append(attempt());stop()
            replacement=store.create('membership');result.update(replacement=replacement.seq,old=attempt())
            results.append(result)
        finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(results))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_append.mts','Actual V4 batch planning, all-or-none log/surface and dispatch validation, complete-batch observer view, reentry and deferred detach; prepared/announcement/removed store write admission.',
        [Path(__file__).resolve(),*[ROOT/'dsh/core/session'/name for name in ('current_append.py','current_session.py','current_surface.py')],
         ROOT/'reference/packages/core/session/src/index.ts',
         ROOT/'reference/packages/core/session/src/surface.ts'],prepare)
