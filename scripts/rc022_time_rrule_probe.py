"""Actual fixed bounded RRULE parser and occurrence windows versus Native."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_schedule_cron_probe import normalize
from dsh.util_time_instant import parse_offset_instant


def rule(body,start='DTSTART:20260916T010000Z'):return start+'\nRRULE:'+body
def epoch(value):return parse_offset_instant(value)['epoch']


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    for expression in ['', 'RRULE:FREQ=DAILY','RRULE:FREQ=DAILY\nDTSTART:20260916T010000Z',
            'DTSTART:20260916T010000Z\nEXDATE:20260917T010000Z',' DTSTART:20260916T010000Z\r\n\n RRULE:FREQ=DAILY \n']:
        add('parse',expression)
    for start in ['DTSTART:00991231T000000Z','DTSTART:20260230T010000Z','DTSTART:20261301T010000Z',
            'DTSTART:20260916T240000Z','DTSTART:20260916T016000Z','DTSTART:20260916T010060Z',
            'DTSTART:20260916T010000','DTSTART;VALUE=DATE:20260916',
            'DTSTART;TZID=America/New_York:20260308T023000','DTSTART;TZID=Unknown/Zone:20260916T010000',
            'DTSTART;TZID=EST:20260916T010000','DTSTART;TZID=US/Eastern:20260916T010000','DTSTART:01000101T000000Z']:
        add('parse',rule('FREQ=DAILY',start))
    bodies=['NOT_A_RULE','=DAILY','FREQ=','FREQ=DAILY;','FREQ=DAILY;FREQ=WEEKLY','freq=daily',
        'FREQ=DAILY;BYEASTER=0','INTERVAL=2','FREQ=NOTREAL','FREQ=constructor','FREQ=SECONDLY;INTERVAL=300',
        'FREQ=DAILY;INTERVAL=0','FREQ=DAILY;INTERVAL=-1','FREQ=DAILY;INTERVAL=9007199254740992',
        'FREQ=DAILY;INTERVAL=9007199254740991','FREQ=DAILY;COUNT=0','FREQ=DAILY;COUNT=1001','FREQ=DAILY;COUNT=1000',
        'FREQ=DAILY;UNTIL=20260917T010000','FREQ=DAILY;UNTIL=20260230T010000Z','FREQ=DAILY;UNTIL=00991231T000000Z',
        'FREQ=WEEKLY;WKST=XX','FREQ=DAILY;BYSECOND=-1','FREQ=DAILY;BYSECOND=0,30','FREQ=DAILY;BYMINUTE=60',
        'FREQ=DAILY;BYHOUR=9,','FREQ=MONTHLY;BYMONTHDAY=0','FREQ=YEARLY;BYYEARDAY=367','FREQ=YEARLY;BYWEEKNO=+54',
        'FREQ=YEARLY;BYMONTH=13','FREQ=MONTHLY;BYDAY=MO;BYSETPOS=0','FREQ=DAILY;BYHOUR=12,12',
        'FREQ=MONTHLY;BYMONTHDAY=1,+1','FREQ=DAILY;BYDAY=XX','FREQ=MONTHLY;BYDAY=0MO','FREQ=YEARLY;BYDAY=54MO',
        'FREQ=MONTHLY;BYDAY=2TU,+2TU','FREQ=DAILY;COUNT=2;UNTIL=20261001T000000Z','FREQ=MINUTELY;BYSECOND=0',
        'FREQ=HOURLY;BYDAY=MO','FREQ=MONTHLY;BYWEEKNO=1','FREQ=DAILY;BYYEARDAY=1','FREQ=WEEKLY;BYMONTHDAY=1',
        'FREQ=WEEKLY;BYDAY=1MO','FREQ=YEARLY;BYWEEKNO=1;BYDAY=1MO','FREQ=MONTHLY;BYSETPOS=1']
    for body in bodies:add('parse',rule(body))
    every_minute='BYHOUR='+','.join(map(str,range(24)))+';BYMINUTE='+','.join(map(str,range(60)))
    add('parse',rule('FREQ=MONTHLY;BYMONTHDAY=1,2,3,4,5,6,7,8;'+every_minute))
    for body,bound in [('FREQ=DAILY;BYHOUR=9,17',2),('FREQ=WEEKLY;BYDAY=MO,WE',2),
            ('FREQ=MONTHLY;BYDAY=MO',5),('FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29,30',2),
            ('FREQ=YEARLY;BYWEEKNO=1',9),('FREQ=YEARLY;BYMONTHDAY=1',12),('FREQ=YEARLY;BYDAY=MO',53),
            ('FREQ=YEARLY;BYMONTH=1,2;BYDAY=MO',10),('FREQ=YEARLY;BYHOUR=1',1)]:
        for position in [bound,-bound,bound+1]:add('parse',rule(body+';BYSETPOS='+str(position)))
    add('parse',rule('FREQ=DAILY;BYHOUR=1;BYSETPOS=1'),dict(rejectIneffectiveSetPositions=True))
    for body,start,after,decision in [
            ('FREQ=DAILY;COUNT=3','DTSTART;TZID=America/New_York:20260307T023000','2026-03-07T00:00:00Z','2026-03-08T12:00:00Z'),
            ('FREQ=DAILY;COUNT=3','DTSTART;TZID=America/New_York:20260307T023000','2026-03-07T00:00:00Z','2026-03-10T12:00:00Z'),
            ('FREQ=DAILY','DTSTART;TZID=America/New_York:20261101T013000','2026-11-01T00:00:00Z','2026-11-01T06:15:00Z'),
            ('FREQ=MINUTELY;INTERVAL=15','DTSTART;TZID=America/New_York:20261101T000000','2026-11-01T00:00:00Z','2026-11-01T06:15:00Z'),
            ('FREQ=WEEKLY;BYHOUR=2,3;BYDAY=WE,SA;BYSETPOS=2,-3;COUNT=4','DTSTART:20260107T020000Z','2026-01-07T00:00:00Z','2026-01-21T12:00:00Z'),
            ('FREQ=DAILY;UNTIL=20260917T010000Z','DTSTART;TZID=Asia/Singapore:20260916T090000','2026-09-16T00:00:00Z','2026-09-18T01:00:00Z'),
            ('FREQ=YEARLY;COUNT=1000;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO','DTSTART:01000101T000000Z','2026-09-16T00:00:00Z','2044-03-01T00:00:00Z'),
            ('FREQ=YEARLY','DTSTART:20260916T010000Z','2026-09-16T00:00:00Z','2026-12-01T00:00:00Z'),
            ('FREQ=DAILY;COUNT=3','DTSTART;TZID=America/Los_Angeles:99991230T200000','2026-09-16T00:00:00Z','9999-12-31T05:00:00Z')]:
        add('journey',rule(body,start),epoch(after),epoch(decision))
    for frequency in ['MINUTELY','HOURLY','DAILY','WEEKLY','MONTHLY','YEARLY']:
        add('next',rule('FREQ='+frequency+';INTERVAL=2'),epoch('2026-09-16T05:06:07Z'))
    for expression in [rule('FREQ=MONTHLY;BYMONTH=2;BYMONTHDAY=30'),
            rule('FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;BYHOUR=2;BYMINUTE=30','DTSTART;TZID=America/New_York:20260307T023000'),
            rule('FREQ=YEARLY;COUNT=5;BYMONTH=3;BYDAY=2SU;BYHOUR=2;BYMINUTE=30','DTSTART;TZID=America/New_York:20260307T023000'),
            rule('FREQ=DAILY;COUNT=1','DTSTART:20250916T000100Z'),
            rule('FREQ=DAILY','DTSTART;TZID=America/Los_Angeles:99991231T200000')]:add('next',expression,epoch('2026-09-16T00:00:00Z'))
    add('next',rule('FREQ=DAILY','DTSTART;TZID=Pacific/Kiritimati:20260916T090000'),epoch('9999-12-31T12:00:00Z'))
    add('next',rule('FREQ=DAILY'),True)
    add('resolve',rule('FREQ=DAILY'),'bad',epoch('2026-09-16T00:00:00Z'))
    add('resolve',rule('FREQ=DAILY'),'2026-09-16T08:00:00.000Z',epoch('2026-09-16T08:30:00Z'))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.util_time_rrule import RRule
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        try:
            parsed=RRule.parse(args[0],args[1] if op=='parse' and len(args)>1 else None)
            if parsed['kind']=='rejected':value=normalize(parsed)
            else:
                current=parsed['rule']
                if op=='parse':value=dict(kind='accepted',expression=current.expression,timeZone=current.timeZone)
                elif op=='next':value=current.next(args[1])
                elif op=='resolve':value=current.resolve(*args[1:])
                else:
                    saved=current.next(args[1]);value=dict(scheduledAt=saved,decision=current.resolve(saved,args[2]))
            rows.append(dict(op=op,args=args,value=value))
        except Exception as error:rows.append(dict(op=op,args=args,error=dict(name=getattr(error,'name',type(error).__name__),message=str(error))))
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_time_rrule.mts',prepare=prepare,scope='Bounded RRULE syntax/cost/defaults, six frequencies, COUNT/UNTIL, duplicate set positions, DST gaps/overlaps, sparse windows, all-gap rules and year-end exhaustion.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/util_time_rrule.py',ROOT/'dsh/util_time_instant.py',ROOT/'dsh/util_time_calendar.py',ROOT/'dsh/javascript/rrule_enumerator.py',ROOT/'dsh/javascript/rrule/manifest.json',
            ROOT/'reference/packages/util/time/src/rrule.ts'])
