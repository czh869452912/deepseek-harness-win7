"""Seven current Schedule records and typed edits against fixed Source."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_time_rrule_probe import epoch,rule

NOW=epoch('2026-09-16T00:00:00Z')
TIMINGS=[dict(kind='after',after_seconds=60),dict(kind='at',at='2026-09-17T00:00:00Z'),dict(kind='every',every_seconds=60),
    dict(kind='daily',daily=dict(time='01:00:00',time_zone='UTC')),
    dict(kind='weekly',weekly=dict(time='01:00:00',time_zone='US/Eastern',weekdays=[7,1,3])),
    dict(kind='cron',cron=dict(expression='0,15,30,45 * * * *',time_zone='UTC')),
    dict(kind='rrule',rrule=rule('FREQ=DAILY;COUNT=3'))]


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    for timing in TIMINGS:
        add('createScheduleRecord','id',' title ',' prompt ',timing,NOW)
        for patch,now,resume in [({},NOW+600000,False),({'title':'new title','prompt':' new prompt '},NOW+600000,False),
                ({'timing':timing},NOW+600000,False),({},NOW+86400000*5,True),
                ({'timing':dict(kind='every',every_seconds=300)},NOW+86400000*5,False),
                ({'title':None},NOW,False),({'prompt':None},NOW,False)]:
            add('editJourney',timing,patch,now,resume)
        add('decodeJourney',timing)
    equivalents=[(TIMINGS[3],dict(kind='daily',daily=dict(time='01:00:00.000',time_zone='Etc/UTC'))),
        (TIMINGS[4],dict(kind='weekly',weekly=dict(time='01:00:00.000',time_zone='America/New_York',weekdays=[1,3,7]))),
        (TIMINGS[5],dict(kind='cron',cron=dict(expression='0-45/15 * * * *',time_zone='UTC')))]
    for before,after in equivalents:add('editJourney',before,dict(timing=after),NOW+864000000,False)
    for timing in [None,{},dict(kind='after'),dict(kind='every',every_seconds=60,after_seconds=1),dict(kind='unknown'),dict(kind='constructor')]:
        add('createScheduleRecord','id','title','prompt',timing,NOW)
    for body in ['FREQ=DAILY;BYHOUR=1;BYSETPOS=1','FREQ=SECONDLY','FREQ=DAILY;COUNT=1']:
        add('createRRuleScheduleRecord','id','title','prompt',rule(body),NOW+86400000*10)
    base=dict(id='id',kind='rrule',title='title',prompt='prompt',rrule=rule('FREQ=DAILY'),scheduledAt='2026-09-16T01:00:00.000Z')
    for patch in [{},{'title':None},{'prompt':' prompt'},{'rrule':123},{'rrule':'bad'},{'rrule':' '+base['rrule']},{'extra':1}]:
        add('decodeScheduleRecord',dict(base,**patch))
    for kind,fields,value in [('at',{},'2026-09-16T01:00:00.999Z'),
            ('daily',dict(timeZone='Asia/Shanghai'),'0001-01-01T00:00:00.999Z'),
            ('cron',dict(timeZone='Europe/Paris'),'1900-01-01T00:00:00.999Z'),
            ('daily',dict(timeZone='Africa/Monrovia'),'1960-01-01T00:00:00.999Z'),
            ('rrule',dict(rrule=rule('FREQ=DAILY','DTSTART;TZID=Pacific/Kiritimati:20260916T090000')),'9999-12-31T23:59:59.999Z')]:
        add('formatScheduleLocalTime',dict(kind=kind,**fields),value)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.schedule import domain_current as domain,update_current as update
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        try:
            if op in ('editJourney','decodeJourney'):
                current=update.create_schedule_record('id','title','prompt',args[0],NOW)
                revised=update.update_schedule_record(current,*args[1:]) if op=='editJourney' else domain.decode_schedule_record(current)
                value=dict(current=current,record=revised,same=revised is current)
            else:value=getattr(update,op)(*args) if hasattr(update,op) else getattr(domain,op)(*args)
            rows.append(dict(op=op,args=args,value=value))
        except Exception as error:rows.append(dict(op=op,args=args,error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=str(error))))
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_update.mts',prepare=prepare,
        scope='Seven authoritative Schedule records, typed timing construction, equivalent edits/identity, rearming/resume errors, RRULE decoding and zone-based display.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/domain_current.py',ROOT/'dsh/schedule/update_current.py',
            ROOT/'reference/packages/schedule/schedule/src/domain.ts',ROOT/'reference/packages/schedule/schedule/src/update.ts'])
