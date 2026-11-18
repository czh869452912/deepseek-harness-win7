"""Current daily/weekly rules against Source Temporal calendar walks."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.util_time_instant import parse_offset_instant


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    for value in [[],None,[1,1],[7,1,3],[0],[8],[True],[1.5],['1']]:add('normalizeWeekdays',value)
    for value in [{},None,dict(time='24:00:00',time_zone='UTC'),dict(time='23:59:60',time_zone='UTC'),
            dict(time='12:30:00.1',time_zone='US/Eastern'),dict(time='12:30:00',time_zone=None),
            dict(time='12:30:00\n',time_zone='UTC'),dict(time='12:30:00',time_zone='Unknown/Zone'),
            dict(time='12:30:00',time_zone='UTC',extra=1)]:
        add('parseDailyInput',value)
        weekly=dict(value,weekdays=[7,1]) if isinstance(value,dict) else value
        add('parseWeeklyInput',weekly)
    for selector in ['daily','weekly']:
        for zone,time,start,decision in [
                ('UTC','12:00:00','2024-01-01T12:00:00Z','2024-02-01T12:00:00Z'),
                ('America/New_York','02:30:00','2024-03-09T08:00:00Z','2024-03-11T08:00:00Z'),
                ('America/New_York','01:30:00','2024-11-02T08:00:00Z','2024-11-03T06:45:00Z'),
                ('Australia/Lord_Howe','02:15:00','2024-10-04T18:00:00Z','2024-10-07T18:00:00Z'),
                ('Pacific/Apia','12:00:00','2011-12-29T23:00:00Z','2011-12-31T23:00:00Z'),
                ('Asia/Shanghai','00:00:00','0001-01-01T00:00:00Z','0001-01-02T00:00:00Z'),
                ('America/New_York','23:59:59.999','9999-12-25T00:00:00Z','9999-12-31T23:59:59.999Z'),
                ('Pacific/Kiritimati','00:00:00','9999-12-29T00:00:00Z','9999-12-31T23:59:59.999Z')]:
            value=dict(time=time,time_zone=zone)
            if selector=='weekly':value['weekdays']=[7,1,2,3,4,5,6]
            now=parse_offset_instant(start)['epoch'];accepted=parse_offset_instant(decision)['epoch']
            add('create'+selector.title()+'ScheduleRecord','id',' prompt ',value,now,' title ')
            add('journey',selector,value,now,accepted)
        for now in [253402300799999,0.5,True]:
            value=dict(time='12:00:00',time_zone='UTC')
            if selector=='weekly':value['weekdays']=[1]
            add('create'+selector.title()+'ScheduleRecord','id','prompt',value,now,'title')
        base=dict(id='id',kind=selector,title='title',prompt='prompt',time='12:30:00.000',timeZone='US/Eastern',scheduledAt='2024-01-01T00:00:00.000Z')
        if selector=='weekly':base['weekdays']=[1,3,7]
        for patch in [{},{'title':None},{'extra':1},{'time':'12:30:00'},{'time':'24:00:00'},{'timeZone':'Unknown/Zone'},{'prompt':' prompt'}]:
            add('decodeWallRecord',dict(base,**patch))
        if selector=='weekly':
            for weekdays in [[7,1],[1,1],[],[True]]:add('decodeWallRecord',dict(base,weekdays=weekdays))
        add('resolve'+selector.title()+'Occurrence',base,1704067199999)
        add('resolve'+selector.title()+'Occurrence',base,0.5)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.schedule import domain_current as domain
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        try:
            if op=='journey':
                selector,value,now,decision=args
                record=getattr(domain,'create'+selector.title()+'ScheduleRecord')('id','prompt',value,now,'title')
                result=getattr(domain,'resolve'+selector.title()+'Occurrence')(record,decision)
            else:result=(domain.decode_wall_record if op=='decodeWallRecord' else getattr(domain,op))(*args)
            rows.append(dict(op=op,args=args,value=result))
        except Exception as error:rows.append(dict(op=op,args=args,error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=str(error))))
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_schedule_wall.mts',prepare=prepare,
        scope='Daily/weekly strict selector and durable record validation, explicit weekday sets, creation and latest-only dispatch with gaps/overlaps/skipped dates and four-digit boundary exhaustion.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/schedule/domain_current.py',ROOT/'dsh/util_time_calendar.py',ROOT/'dsh/util_time_instant.py',
            ROOT/'reference/packages/schedule/schedule/src/domain.ts'])
