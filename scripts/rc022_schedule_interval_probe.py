"""Current one-shot/fixed-rate Host record contract, with actual Source calls."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
NOW=1704067200000


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    for value in [None,'',' \ufeff',' a ','x'*120,'x'*121,'😀'*60,'😀'*61,' x','x\u0085']:
        add('scheduleTitle',value);add('decodeStoredTitle',value)
    for seconds in [1,0,-1,0.5,True,60,59,300,9007199254740991,9007199254740992]:
        add('createAfterScheduleRecord','id',' prompt ',seconds,NOW,' title ')
        add('createEveryScheduleRecord','id',' prompt ',seconds,NOW,' title ')
    for at in ['2024-01-01T00:00:00Z','2024-01-01T00:00:01+00:00','2024-02-30T00:00:00Z',
            '2024-01-01T00:00:01-00:00','0001-01-01T00:00:00+01:00',None,{},
            dict(date='2024-03-10',time='02:30:00',time_zone='America/New_York'),
            dict(date='2024-11-03',time='01:30:00',time_zone='US/Eastern'),
            dict(date='2024-02-30',time='00:00:00',time_zone='Unknown/Zone'),
            dict(date='2024-01-01',time='00:00:00',time_zone=None),
            dict(date=2024,time='00:00:00',time_zone='UTC')]:
        add('parseAtInput',at);add('createAtScheduleRecord','id','prompt',at,NOW,'title')
    base=dict(id='task',kind='every',title='title',prompt='prompt',everySeconds=60,scheduledAt='2024-01-01T00:01:00.000Z')
    for patch in [{},{'extra':1},{'title':None},{'title':' title '},{'prompt':' prompt'},
            {'id':' task'},{'everySeconds':59},{'everySeconds':9007199254740},
            {'scheduledAt':'2024-02-30T00:00:00.000Z'},{'scheduledAt':'0001-01-01T00:00:00.000Z'}]:
        add('decodeIntervalRecord',dict(base,**patch))
    for kind in ['at','after']:
        record=dict(base,kind=kind);record.pop('everySeconds')
        if kind=='after':record['afterSeconds']=1
        add('decodeIntervalRecord',record);add('decodeIntervalRecord',dict(record,extra=1))
    for now in [NOW,NOW+60000,NOW+61000,NOW+3600000000,253402300799999,0.5,True]:
        add('resolveEveryOccurrence',base,now)
    for epoch,now in [(NOW,NOW),(NOW+1,NOW),(253402300799999,0),(253402300800000,0),(-62135596800000,-62135596800001),(NOW,0.5)]:
        add('futureInstant',epoch,now)
    framed=dict(id='a"\n😀',prompt='a"\n</tag>\u2028',scheduledAt=base['scheduledAt'])
    add('renderReminderFraming',framed)
    add('renderRecurringReminderBatchFraming',[dict(record=framed,occurrenceAt=base['scheduledAt']),dict(record=base,occurrenceAt='9999-12-31T23:59:59.999Z')])
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.schedule import domain_current as domain
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        fn=domain.decode_interval_record if op=='decodeIntervalRecord' else getattr(domain,op)
        try:rows.append(dict(op=op,args=args,value=fn(*args)))
        except Exception as error:rows.append(dict(op=op,args=args,error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=str(error))))
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_interval.mts',prepare=prepare,
        scope='Current after/at/every constructors, durable decoding, title/instant boundaries, latest-only fixed-rate decisions and escaped delivery framing; errors preserve exact names/codes/messages.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/domain_current.py',ROOT/'dsh/util_time_instant.py',
            ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/schedule/schedule/src/domain.ts'])
