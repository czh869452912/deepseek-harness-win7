"""Observe fiber-owned message definitions across store create, fork and restore."""
import copy
import inspect
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    rows=[]
    for action in ('unload','dispose','duplicate','unrelated'):
        ctx=Context();held={}
        def project(event,context):
            seq=event['data']['seq']
            original=context.messages.get(seq,context.events[int(seq-context.baseSeq)]['data'])
            return {seq:dict(original,content=[dict(type='text',text=event['data']['text'])])}
        definition=dict(type='test/project',project=project)
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Owner(Plugin):
            inject=['sessions']
            def apply(self,owner):held['dispose']=owner.get('sessions').registerMessageProjection(definition)
        try:
            await ctx.plugin(Store);fiber=await ctx.plugin(Owner)
            store=ctx.get('sessions');borrowed=store.messageProjections
            result=dict(name=action,registered=[item['type'] for item in borrowed])
            if action=='duplicate':
                try:store.registerMessageProjection(dict(definition))
                except Exception as error:result['duplicate']=str(error)
            live=store.create('live');live.append_user_message('original')
            live.append('test/project',dict(seq=0,text='changed'))
            pending=store.create('pending');pending.append_user_message('original')
            pending.append('test/project',dict(seq=0,text='pending'))
            before=live.deriveMessages();child=store.fork(live)
            restored=store.prepare('restored',dict(seed=live.snapshotEvents(),meta=dict(live.header.to_dict(),id='restored'),
                inheritedEventCount=live.inheritedEventCount,eventState='shared-frozen'))
            detach=store.enter(restored);ctx.disposable(detach);store.announce(restored)
            result['before']=[session.deriveMessages()[0]['content'] for session in (live,child,restored)]
            if action=='dispose':
                returned=held['dispose']()
                if inspect.isawaitable(returned):await returned
            elif action=='unrelated':
                other=store.registerMessageProjection(dict(type='test/unused',project=project))
                returned=other()
                if inspect.isawaitable(returned):await returned
            else:await fiber.dispose()
            result.update(remaining=[item['type'] for item in borrowed],sameBorrowed=store.messageProjections is borrowed,
                          snapshotRetained=before[0]['content'][0]['text']=='changed',outcomes=[])
            for session in (live,pending,child,restored):
                outcomes=[]
                for callback in (session.deriveMessages,lambda:session.deriveEventMessage(session.eventAt(0)),
                                 lambda:session.surface.replaceGeneration,lambda:session.surface.contentGeneration,
                                 lambda:session.append('turn/start',dict(turn=1))):
                    try:callback();outcomes.append('value')
                    except Exception as error:outcomes.append(str(error))
                result['outcomes'].append(outcomes)
            rows.append(result)
        finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_projection_store.mts','Actual Context-owned registration and disposal; create/fork/shared-frozen restore retain one borrowed definition list and reject cached or pending interpretation after owner removal.',
        [Path(__file__).resolve(),ROOT/'dsh/core/session/current_session.py',ROOT/'dsh/core/session/current_surface.py',
         ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/core/session/src/index.ts'])
