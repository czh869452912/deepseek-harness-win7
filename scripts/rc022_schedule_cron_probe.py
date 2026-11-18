"""Shared Cron engine and its current Schedule consumers, paired to fixed Source."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.util_time_instant import parse_offset_instant


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    expressions=['0 0 * * *','*/15 9-17 * * 1-5','30,10,20 * * * *','1,2,5 0 * * *',
        '0,0,30 * * * *','*/1 * * * *','0 0 1-31 * 0-7','0 0 */2 * */2','0 0 *,2 * 7',
        '0 0 1,3,5,7,9 * 0,7','0 0 */3,2,4 * 1-5','0\t0\ufeff* * *','0 0 * * 7',
        '',' 0 0 * * *','0 0 * * *\n','* * * *','* * * * * *','@daily',None,
        '60 * * * *','-1 * * * *','1/2 * * * *','*/0 * * * *','*/9007199254740992 * * * *',
        '2-1 * * * *','1,,2 * * * *','1-2/0 * * * *','１ * * * *','0 0 * JAN MON']
    for value in ['*','*/2','*/3,2','1-5','1,2,5','0,7','2-4/2']:
        expressions.append('0 0 '+value+' * '+value)
    for expression in expressions:
        add('parse',expression,'UTC');add('canonicalizeCronExpression',expression)
    for zone in ['US/Eastern','asia/shanghai','Etc/UTC','Unknown/Zone',' UTC','GMT']:
        add('parse','*/15 * * * *',zone)
    for expression,zone,start,decision in [
            ('45 1 * * 0','America/New_York','2026-10-25T05:45:00Z','2026-11-01T06:30:00Z'),
            ('30 2 * * *','America/New_York','2024-03-09T08:00:00Z','2024-03-11T08:00:00Z'),
            ('30 0 * * *','Pacific/Kiritimati','2025-12-31T00:00:00Z','2026-01-01T11:00:00Z'),
            ('*/7 * * * *','UTC','2024-01-01T00:00:00Z','2026-11-01T06:30:00Z'),
            ('0 0 29 2 *','UTC','2023-03-01T00:00:00Z','2029-01-01T00:00:00Z'),
            ('0 0 */2 * 1','UTC','2024-01-01T00:00:00Z','2024-02-01T23:59:59Z'),
            ('0 0 1-31 * 1','UTC','2024-01-01T00:00:00Z','2024-02-01T23:59:59Z'),
            ('0 12 * * *','Pacific/Apia','2011-12-29T23:00:00Z','2011-12-31T23:00:00Z'),
            ('0 0 * * *','America/New_York','0001-01-01T00:00:00Z','0001-01-01T06:00:00Z'),
            ('0 0 * * *','Asia/Shanghai','0001-01-01T00:00:00Z','0001-01-02T06:00:00Z'),
            ('59 23 * * *','America/New_York','9999-12-29T00:00:00Z','9999-12-31T23:59:59.999Z'),
            ('0 0 * * *','Pacific/Kiritimati','9999-12-29T00:00:00Z','9999-12-31T23:59:59.999Z')]:
        now=parse_offset_instant(start)['epoch'];accepted=parse_offset_instant(decision)['epoch']
        add('journey',expression,zone,now,accepted)
        add('createCronScheduleRecord','id',' prompt ',dict(expression=expression,time_zone=zone),now,' title ')
    for expression,zone in [('0 0 30 2 *','UTC'),('0 0 * * *','UTC')]:add('next',expression,zone,253402300799999 if expression.endswith('* * *') else 1704067200000)
    for after in [True,0.5,253402300800000]:add('next','0 0 * * *','UTC',after)
    for saved,accepted in [('2024-01-01T00:00:00.000Z',0),('bad',1704067200000),('2024-01-01T00:00:00.000Z',True)]:add('resolve','0 0 * * *','UTC',saved,accepted)
    base=dict(id='id',kind='cron',title='title',prompt='prompt',expression='*/15 * * * *',timeZone='UTC',scheduledAt='2024-01-01T00:00:00.000Z')
    for patch in [{},{'expression':'0,15,30,45 * * * *'},{'expression':'bad'},{'timeZone':'Unknown/Zone'},{'title':None},{'extra':1}]:add('decodeCronRecord',dict(base,**patch))
    for value in [{},dict(expression='* * * * *',time_zone=None),dict(expression='* * * * *',time_zone='US/Eastern')]:add('parseCronInput',value)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


def normalize(value):
    if isinstance(value,Exception):return dict(name=getattr(value,'name',type(value).__name__),message=str(value))
    if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
    if isinstance(value,list):return [normalize(item) for item in value]
    return value


async def observe():
    from dsh.util_time_cron import Cron
    from dsh.schedule import domain_current as domain
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        try:
            if op in ('parse','next','resolve','journey'):
                parsed=Cron.parse(*args[:2])
                if parsed['kind']=='rejected':result=parsed
                else:
                    rule=parsed['rule']
                    if op=='parse':result=dict(kind='accepted',fields=rule.fields,timeZone=rule.timeZone,expression=rule.expression)
                    elif op=='next':result=rule.next(args[2])
                    elif op=='resolve':result=rule.resolve(*args[2:])
                    else:
                        saved=rule.next(args[2]);result=dict(scheduledAt=saved,decision=rule.resolve(saved,args[3]))
            else:result=(domain.decode_cron_record if op=='decodeCronRecord' else getattr(domain,op))(*args)
            rows.append(dict(op=op,args=args,value=normalize(result)))
        except Exception as error:rows.append(dict(op=op,args=args,error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=str(error))))
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_cron.mts',prepare=prepare,
        scope='Actual shared Cron fields/canonicalization, strict errors, Vixie semantics, 400-year horizon, zone-aware latest/next and Schedule record consumers.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/util_time_cron.py',ROOT/'dsh/util_time_recurrence.py',ROOT/'dsh/util_time_calendar.py',ROOT/'dsh/schedule/domain_current.py',
            ROOT/'reference/packages/util/time/src/cron.ts',ROOT/'reference/packages/schedule/schedule/src/domain.ts'])
