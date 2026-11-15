"""Observe title input handles and provider revisions on actual V4 Sessions."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CONFIG=dict(fallbackMaxWords=5,fallbackMaxBytes=40,maxTitleBytes=80)

def message(text):
    return dict(id='input',role='user',content=[dict(type='text',text=text)],source=dict(kind='user'))

def normalization_cases():
    texts=['','  hello\tworld\n next ','中文 标题 测试','😀abc','\ud800abc','\udfff','a\u200bb\u2066c\ufeff','\x1b[31mred\x1b[0m','a\x1b]0;hidden\x07b','a\x1b]unterminated','a\x9b31mb','a\x85b','a\u00a0b','a\u2028b','a\u180eb','x'*121]
    return [dict(text=text,bytes=limit) for text in texts for limit in (1,2,3,4,8,40,80)]

def input_schema_cases():
    empty=dict(first=None,count=0,lastSeq=None);first=dict(seq=0,text='first');populated=dict(first=first,count=1,lastSeq=0)
    return [empty,populated,dict(populated,first=dict(seq=0,text='')),dict(populated,first=dict(seq=1,text='late')),
            dict(empty,count=1),dict(populated,count=0),dict(populated,lastSeq=None),dict(populated,count=1.5),
            dict(populated,count=True),dict(populated,count=9007199254740992),dict(populated,count=9007199254740991),
            dict(populated,lastSeq=9007199254740992),dict(populated,extra=True),dict(populated,first=dict(first,extra=True)),
            dict(populated,first=dict(seq=-1,text='bad')),dict(populated,count=1.0)]

def result_cases():
    valid=dict(title='  Accepted title  ',messageSeqs=[0])
    return [None,3,[],{},dict(valid,title=None),dict(valid,title='\u200b'),dict(valid,messageSeqs=[]),
            dict(valid,messageSeqs=[99]),dict(valid,messageSeqs=[0,0]),dict(valid,messageSeqs=[2,0]),
            dict(valid,messageSeqs=[True]),dict(valid,messageSeqs=[0.0]),dict(valid,messageSeqs=[0,2]),
            dict(valid,model=None),dict(valid,model={}),dict(valid,model=dict(provider='',model='m')),
            dict(valid,model=dict(provider='p',model='m',extra=True)),valid]

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.session.canonical_title import SessionTitleService,TITLE_INPUT_PROJECTION_DEFINITION
    from dsh.session.title import normalize_session_title,fallback_session_title,truncate_title_utf8
    rows=[]
    for test in normalization_cases():
        rows.append(dict(normalize=normalize_session_title(test['text'],test['bytes']),fallback=fallback_session_title(test['text'],2,test['bytes']),truncate=truncate_title_utf8(test['text'],test['bytes'])))
    with patch.object(CurrentSession,'_event_time',return_value=1000):
        for action in ('fallback','provider-current','watermark','replacement','activation-title','activation-input','rename-queued',
                       'eligibility-root','eligibility-parent','eligibility-seeded','eligibility-subagent'):
            ctx=Context();releases=[]
            class Store(Plugin):
                def apply(self,owner):CurrentSessionStore(owner,4)
            class Registry(Plugin):
                def apply(self,owner):SessionProjectionRegistry(owner,4)
            try:
                await ctx.plugin(Store);await ctx.plugin(Registry);await ctx.plugin(CurrentAgentPlugin)
                projections=ctx.get('sessionProjections');row=dict(action=action);written=asyncio.Event()
                ctx.on('session/event',lambda session,event:written.set() if event['type']=='session/title' else None)
                if action.startswith('activation-'):
                    entered=asyncio.Event();release=asyncio.Event();releases.append(release);original=SessionProjectionRegistry.register
                    async def delayed(registry,definition):
                        handle=await original(registry,definition)
                        if definition['key']==('title' if action=='activation-title' else 'titleInput'):
                            entered.set();await release.wait()
                        return handle
                    # Preserve the traced method receiver while gating readiness.
                    with patch.object(SessionProjectionRegistry,'register',delayed):
                        fiber=ctx.plugin(SessionTitleService,CONFIG);await entered.wait();row['hidden']=ctx.get('sessionTitle') is None;session=ctx.get('sessions').create('title');session.append('user/message',message('First during activation'),'append');session.append('user/message',message('Second during activation'),'append');release.set();await fiber
                    await asyncio.wait_for(written.wait(),2);titles=ctx.get('sessionTitle');row['title']=titles.get(session)
                else:
                    await ctx.plugin(SessionTitleService,CONFIG);titles=ctx.get('sessionTitle')
                    meta = (dict(parentSession='parent') if action=='eligibility-parent' else
                            dict(parentSession='parent',isSeeded=True) if action=='eligibility-seeded' else
                            dict(parentSession='parent',origin='subagent',delegationDepth=1) if action=='eligibility-subagent' else {})
                    session=ctx.get('sessions').create('title',dict(meta=meta,**(dict(seed=[],inheritedEventCount=0) if action=='eligibility-seeded' else {})));requests=[]
                    async def generate(request):
                        requests.append(dict(messages=request['messages'],**{key:request[key] for key in ('route','currentTitle') if key in request}))
                        return dict(title='Generated',messageSeqs=[m['seq'] for m in request['messages']])
                    if action=='watermark' or action.startswith('eligibility-'):titles.register(dict(id='provider',automatic='first-prompt',generate=generate))
                    session.append('user/message',message('First human prompt'),'append')
                    if action.startswith('eligibility-'):
                        session.append('request/header',dict(header=dict(config=dict(provider='main',model='model')),reason='initial'))
                        await titles._drain(titles.tasks);row['requests']=requests;row['title']=titles.get(session)
                    elif action=='watermark':
                        session.append('request/header',dict(header=dict(config=dict(provider='main',model='model')),reason='initial'))
                        session.append('user/message',message('Second before provider'),'append')
                        await titles._drain(titles.tasks)
                        row['requests']=requests;row['title']=titles.get(session)
                    elif action=='rename-queued':
                        pending=asyncio.create_task(titles.refresh(session));await asyncio.sleep(0);titles.rename(session,'Pinned');row['title']=await pending
                        await titles._drain(titles.tasks)
                    elif action=='replacement':
                        await asyncio.wait_for(written.wait(),2);entered=asyncio.Event();release=asyncio.Event();releases.append(release)
                        async def old(request):
                            entered.set();await release.wait();return dict(title='Late old title',messageSeqs=[request['messages'][0]['seq']])
                        dispose=titles.register(dict(id='old',automatic='first-prompt',generate=old));pending=asyncio.create_task(titles.refresh(session));await entered.wait();closing=asyncio.ensure_future(dispose());await asyncio.sleep(0);row['draining']=not closing.done()
                        titles.register(dict(id='replacement',automatic='first-prompt',generate=generate));row['new']=await titles.refresh(session);release.set();await closing
                        try:await pending
                        except Exception as error:row['oldError']=str(error)
                        row['title']=titles.get(session)
                    elif action=='provider-current':
                        await asyncio.wait_for(written.wait(),2);titles.register(dict(id='provider',automatic='all-prompts',generate=generate));row['title']=await titles.refresh(session);row['requests']=requests
                    else:
                        await asyncio.gather(*(titles.refresh(session) for _ in range(3)))
                        row['title']=titles.get(session)
                await titles._drain(titles.tasks)
                checkpoint=projections.checkpoint(session);row['input']=checkpoint['titleInput'];row['summary']=sorted(projections.summaryKeys());row['titleEvents']=[e['data'] for e in session.snapshotEvents() if e['type']=='session/title']
                rows.append(row)
            finally:
                for release in releases:release.set()
                await ctx.fiber.dispose()
    for state in input_schema_cases():
        try:row=dict(schema=True,value=TITLE_INPUT_PROJECTION_DEFINITION['stateSchema'](state))
        except Exception:row=dict(schema=False)
        rows.append(row)
    for result in result_cases():
        try:
            title,seqs,model=SessionTitleService._validate_result(SimpleNamespace(format_version=4,config=CONFIG),result,[dict(seq=0,text='first'),dict(seq=2,text='second')])
            row=dict(result=dict(title=title,messageSeqs=seqs,**({} if model is None else dict(model=model))))
        except Exception as error:row=dict(error=str(error))
        rows.append(row)
    return json.loads(json.dumps(rows))

def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(dict(normalization=normalization_cases(),schemas=input_schema_cases(),results=result_cases())),encoding='utf-8');return [path]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_title.mts','Title normalization, host-only input state v3, concurrent fallback, activation-time input, provider snapshot watermarks and replacement during drain.',[Path(__file__).resolve(),ROOT/'dsh/session/canonical_title.py',ROOT/'dsh/session/title.py'],prepare=prepare)
