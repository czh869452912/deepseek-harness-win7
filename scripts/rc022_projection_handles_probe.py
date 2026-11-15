"""Observe asynchronous registration and independently retained readers."""
import asyncio
import inspect
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.core.session.json import UNDEFINED
    from dsh.session.projections import SessionProjectionRegistry
    rows=[]
    for action in ('retained','shared','lazy','summary','conflicts','legacy','return','effect','yield','drive','listener-failure','unit-failure','handoff','mutated','reader-failure','undefined','double-release'):
        ctx=Context();held={};calls={};changes=[];events=[]
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Registry(Plugin):
            def apply(self,owner):SessionProjectionRegistry(owner,4)
        def definition(key='count',version=1,step=1,wire=True,summary=True):
            calls.setdefault(key,dict(init=0,apply=0))
            def init(header,cut):calls[key]['init']+=1;return 0
            def apply(state,event):
                calls[key]['apply']+=1
                if action=='unit-failure' and key=='second':raise ValueError('unit failed')
                return state+step
            value=dict(key=key,stateVersion=version,stateSchema=lambda value:value,init=init,apply=apply)
            if wire:value['wire']=dict(viewSchema=lambda value:value,view=lambda value:value,summary=summary)
            return value
        class Owner(Plugin):
            inject=['sessionProjections']
            def apply(self,owner):
                held['owner']=owner;registration=owner.get('sessionProjections').register(definition());held['registration']=registration
                if action=='return':return registration
                if action=='effect':owner.effect(lambda:registration)
                if action=='yield':
                    def setup():yield registration
                    owner.effect(setup)
        try:
            await ctx.plugin(Store);await ctx.plugin(Registry)
            store=ctx.get('sessions');registry=ctx.get('sessionProjections');session=store.create('live')
            owner=await ctx.plugin(Owner);handle=await held['registration'];row=dict(action=action)
            def append():session.append('turn/start',dict(turn=session.seq+1))
            if action=='retained':
                reader=handle.readerFor(session);row['before']=dict(calls['count']);await owner.dispose()
                row['unreadReleased']=registry.checkpoint(session);append();row['retained']=reader();row['released']=registry.checkpoint(session)
                replacement=await registry.register(definition(version=2,step=10));row['old']=reader();row['new']=replacement.stateOf(session);row['checkpoint']=registry.checkpoint(session)
            elif action=='shared':
                second=await registry.register(definition());append();row['initial']=[handle.stateOf(session),second.stateOf(session)]
                await handle.dispose();append();row['one']=registry.snapshot(session);await second.dispose();append();row['releasedBefore']=registry.checkpoint(session)
                row['old']=handle.stateOf(session);row['releasedAfter']=registry.checkpoint(session);row['floor']=registry.restoreFloor({});row['snapshot']=registry.snapshot(session)
            elif action=='lazy':
                await registry.register(definition('unrelated',wire=False));reader=handle.readerFor(session);row['before']=json.loads(json.dumps(calls));row['value']=reader();row['after']=json.loads(json.dumps(calls))
                other=store.create('other');other.append('turn/start',dict(turn=1));row['bound']=[reader(),handle.readerFor(other)()]
            elif action=='summary':
                await registry.register(definition('excluded',summary=False));await registry.register(definition('host',wire=False));keys=registry.summaryKeys();second=await registry.register(definition());row['sharedStable']=keys is registry.summaryKeys()
                row['snapshot']=registry.snapshot(session,keys);row['calls']=json.loads(json.dumps(calls));await second.dispose();row['partialStable']=keys is registry.summaryKeys();await handle.dispose();row['keys']=sorted(registry.summaryKeys());row['invalidated']=keys is not registry.summaryKeys()
            elif action=='conflicts':
                row['errors']=[]
                for value in (definition(version=2),definition(summary=False),definition(wire=False),definition('bad',version=-1),definition('bad',version=1.5),definition('bad',version=True)):
                    registration=registry.register(value)
                    try:await registration
                    except Exception as error:row['errors'].append(str(error))
                    returned=registration()
                    if inspect.isawaitable(returned):await returned
                row['snapshot']=registry.snapshot(session)
            elif action=='legacy':
                returned=held['registration']()
                if inspect.isawaitable(returned):await returned
                append();row.update(value=handle.stateOf(session),snapshot=registry.snapshot(session),checkpoint=registry.checkpoint(session))
            elif action in ('return','effect','yield'):
                row['before']=registry.snapshot(session);await owner.dispose();append();row['after']=registry.snapshot(session);row['retained']=handle.stateOf(session)
            elif action in ('drive','listener-failure','unit-failure'):
                await registry.register(definition('second'))
                def changed(s,key,value,seq):
                    changes.append([key,value,seq])
                    if action=='listener-failure':raise ValueError('listener failed')
                registry.onChanged(changed);registry.onEventChanged(lambda s,value,seq:events.append([value,seq]));append();row.update(changes=changes,events=events,checkpoint=registry.checkpoint(session) if action!='unit-failure' else None)
            elif action=='mutated':
                value=definition('mutable');wire=value['wire'];mutable=await registry.register(value)
                value['init']=lambda header,cut:5;value['apply']=lambda state,event:state+10;wire['view']=lambda state:state*2
                row['before']=mutable.stateOf(session);append();row['after']=registry.snapshot(session)
            elif action=='reader-failure':
                failure=ValueError('reader cannot initialize');value=definition('broken')
                def broken(header,cut):raise failure
                value['init']=broken;broken_handle=await registry.register(value);reader=broken_handle.readerFor(session)
                row['before']=dict(calls['broken'])
                try:reader()
                except Exception as error:row.update(error=str(error),same=error is failure)
            elif action=='undefined':
                value=definition('optional',wire=False);value['init']=lambda header,cut:UNDEFINED;value['apply']=lambda state,event:event['data']['turn'];optional=await registry.register(value)
                row['undefined']=optional.readerFor(session)() is UNDEFINED;append();row['value']=optional.stateOf(session)
            elif action=='double-release':
                second=await registry.register(definition());await handle.dispose();await handle.dispose();await owner.dispose();append();row['before']=registry.snapshot(session)
                await second.dispose();await second.dispose();row['after']=registry.snapshot(session)
            elif action=='handoff':
                registration=held['owner'].get('sessionProjections').register(definition('handoff'));disposed=owner.dispose()
                try:await registration;row['exposed']=True
                except Exception as error:row['error']=str(error)
                if inspect.isawaitable(disposed):await disposed
                row['snapshot']=registry.snapshot(session)
            rows.append(row)
        finally:await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_projection_handles.mts','Awaited effect-owned projection handles, retained exact-Session readers, released checkpoints, lazy selected snapshots, summary membership, conflicts, legacy composition and event-level changes.',[Path(__file__).resolve(),ROOT/'dsh/session/projections.py'])
