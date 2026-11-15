"""Compare retained Inbox readers against the fixed Source implementation."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

def message(identity):
    return dict(id=identity,role='user',content=[dict(type='text',text=identity)],source=dict(kind='user'))

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.core.inbox_current import ReactLoopInbox,INBOX_PROJECTION_DEFINITION
    from dsh.session.projections import SessionProjectionRegistry
    rows=[]
    for action in ('live','detached','replacement','reader-failure','lazy','independent'):
        ctx=Context()
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Registry(Plugin):
            def apply(self,owner):SessionProjectionRegistry(owner,4)
        try:
            await ctx.plugin(Store);await ctx.plugin(Registry)
            registry=ctx.get('sessionProjections');handle=await registry.register(INBOX_PROJECTION_DEFINITION)
            session=CurrentSession.create('inbox',format_version=4) if action=='detached' else ctx.get('sessions').create('inbox')
            row=dict(action=action);notifications=[];reads=[0];primary=RuntimeError('reader failed')
            def read():
                reads[0]+=1
                if action=='reader-failure':raise primary
                return handle.stateOf(session)
            inbox=ReactLoopInbox(read,session,SimpleNamespace(emit=lambda name,payload:notifications.append(dict(name=name,payload=payload))))
            row['constructorReads']=reads[0]
            if action=='reader-failure':
                failures=[]
                for operation in (lambda:inbox.nextTurn,lambda:inbox.hasPending,lambda:inbox.append('next-turn',message('a'))):
                    try:operation()
                    except Exception as error:failures.append(error is primary)
                row.update(failures=failures,eventCount=len(session.events),notifications=notifications);rows.append(row);continue
            if action=='lazy':
                await handle.dispose();row['unread']=registry.checkpoint(session);row['read']=inbox.hasPending;row['after']=registry.checkpoint(session);rows.append(row);continue
            inbox.append('next-turn',message('turn'));inbox.append('next-step',message('step'));captured=inbox.nextStep
            inbox.prepend('next-turn',message('front'));row['replaced']=inbox.replace('turn',message('new'))
            row['missing']=inbox.remove('missing');row['claimed']=inbox.claim('next-turn',5);row['captured']=captured
            row['before']=dict(turn=inbox.nextTurn,step=inbox.nextStep)
            await handle.dispose();row['released']=registry.checkpoint(session)
            if action=='replacement':
                replacement=await registry.register(INBOX_PROJECTION_DEFINITION);row['replacement']=replacement.stateOf(session)
            if action=='independent':
                other=ctx.get('sessions').create('other');second=ReactLoopInbox(handle.readerFor(other),other,SimpleNamespace(emit=lambda *args:None));second.append('next-turn',message('other'));row['other']=second.nextTurn
            inbox.append('next-step',message('retained'));row['retained']=dict(turn=inbox.nextTurn,step=inbox.nextStep)
            inbox.clear();row['cleared']=inbox.hasPending;row['notifications']=notifications
            # Event identity and payloads matter here; wall-clock timestamps do not.
            row['events']=[dict(seq=e['seq'],type=e['type'],data=e['data']) for e in session.snapshotEvents()]
            rows.append(row)
        finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_inbox_readers.mts','Retained Inbox callback laziness, exact reader failures, durable mutations and notifications, independent Sessions and registration replacement.',[Path(__file__).resolve(),ROOT/'dsh/core/inbox_current.py',ROOT/'dsh/core/agent_loop_current.py',ROOT/'dsh/core/agent_loop.py',ROOT/'dsh/core/react_loop_current.py'])
