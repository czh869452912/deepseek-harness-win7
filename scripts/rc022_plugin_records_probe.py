"""Observe experimental record grammar, durable identity and publication ownership."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def names():
    values=['plugin:', 'plugin:Test/state','plugin:/state','plugin:test/','plugin:test//state',
        'plugin:-test','plugin:test state','turn/start','plugin:a','plugin:0/a.0_b-c','plugin:test.bridge/entry_1']
    for character in [chr(index) for index in range(128)]+['é','中','😀','\u2028','\u2029']:
        for template in ('plugin:%s','plugin:a%s','plugin:a/%s','plugin:a%s/b'):
            values.append(template%character)
    return values


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(names()),encoding='utf-8');return [path]


def grammar_rows():
    from dsh.core.session.current_session import CurrentSession,appendPluginRecord,pluginRecordOf
    from dsh.core.session.json import UNDEFINED
    rows=[]
    for name in names():
        session=CurrentSession.create('grammar',format_version=4);result=dict(name=name)
        try:
            result['returned']=appendPluginRecord(session,name,dict(value=1))
            event=session.eventAt(0);record=pluginRecordOf(event)
            result.update(record=record is not UNDEFINED,identical=record['data'] is event['data'],nodes=list(session.surface.nodes))
        except Exception as error:result['error']=str(error)
        result['seq']=session.seq;rows.append(result)
    return rows


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSession,CurrentSessionStore,appendPluginRecord,pluginRecordOf
    from dsh.core.session.json import UNDEFINED
    rows=grammar_rows()
    session=CurrentSession.create('source',format_version=4);session.append_user_message('hello',message_id='user')
    data=dict(count=1,nested=['a',2]);returned=appendPluginRecord(session,'plugin:test/state',data);data['nested'].append('changed');data['count']=2
    events=session.snapshotEvents();record=pluginRecordOf(events[1])
    resumed=CurrentSession.create('resume',events,format_version=4)
    restored=CurrentSession.from_restore(session.id,events,session.header,0,'shared-frozen',format_version=4)
    child=CurrentSession.create('child',events,dict(session.header.to_dict(),id='child',parentSession=session.id,isSeeded=True),len(events),format_version=4)
    rows.append(dict(name='durable',returned=returned,data=record['data'],identical=record['data'] is events[1]['data'],
        copies=[pluginRecordOf(item.snapshotEvents()[1])['data'] for item in (resumed,restored,child)],
        messages=[item.deriveMessages()[0]['content'] for item in (session,resumed,restored,child)],nodes=list(session.surface.nodes),
        notRecord=[pluginRecordOf(dict(type=kind,seq=0,time=0,data={},ignorable=flag)) is UNDEFINED
            for kind,flag in [('turn/start',True),('plugin:a',False),('plugin:a',1),('plugin:',True)]]))
    for label,data in [('nan',float('nan')),('infinity',float('inf')),('negative-zero',-0.0),('undefined',UNDEFINED)]:
        current=CurrentSession.create('lossy',format_version=4)
        try:appendPluginRecord(current,'plugin:test/number',data);error='accepted'
        except Exception as caught:error=str(caught)
        rows.append(dict(name=label,error=error,seq=current.seq))
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    for action in ('normal','failed','veto','reentry','detach'):
        ctx=Context();result=dict(name='ownership-'+action,stages=[],heard=[],reentry=[])
        try:
            await ctx.plugin(Store);store=ctx.get('sessions');session=store.prepare('owned')
            def attempt():
                try:return appendPluginRecord(session,'plugin:test/state',{})
                except Exception as error:return str(error)
            result['stages'].append(attempt());detach=store.enter(session);result['stages'].append(attempt())
            def created(*args):
                result['stages'].append(attempt())
                if action=='failed':raise ValueError('creation observer failed')
            stop_created=ctx.on('session/created',created)
            try:store.announce(session)
            except Exception as error:result['announcement']=str(error)
            def listener(current,event):
                result['heard'].append(dict(type=event['type'],seq=event['seq'],size=current.seq,record=pluginRecordOf(event) is not UNDEFINED))
                if action=='reentry':result['reentry'].append(attempt())
                if action=='detach':detach()
            ctx.on('session/event',listener)
            def dispatch(mode,name,args,receiver=None):
                if action=='veto' and name=='session/event':raise ValueError('record dispatch veto')
            ctx.on('internal/dispatch',dispatch)
            result['stages'].append(attempt());detach();result['stages'].append(attempt());result.update(seq=session.seq,live=store.get(session.id) is session)
            stop_created();replacement=store.create('owned');result['stale']=attempt();result['replacement']=replacement.seq
            rows.append(result)
        finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_plugin_records.mts','Experimental plugin record grammar, lossless snapshot, ignorable read identity, fork/resume/reopen, store announcement ownership and dispatch/reentry/detach atomicity. No production caller added.',
        [Path(__file__).resolve(),ROOT/'dsh/core/session/plugin_records.py',ROOT/'dsh/core/session/current_session.py'],prepare)
