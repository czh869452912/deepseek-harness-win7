"""Strict wall-clock boundaries against the fixed Temporal/Intl implementation."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    def add(op,*args):rows.append(dict(op=op,args=list(args)))
    instants=['0001-01-01T00:00:00.000Z','9999-12-31T23:59:59.999Z',
        '2024-02-29T12:03:04.500Z','2023-02-29T12:03:04.000Z','2024-02-30T12:03:04.000Z',
        '0000-01-01T00:00:00.000Z','2024-01-01T24:00:00.000Z','2024-01-01T23:60:00.000Z',
        '2024-01-01T23:59:60.000Z','2024-00-01T00:00:00.000Z','2024-13-01T00:00:00.000Z',
        '2024-01-00T00:00:00.000Z','2024-01-32T00:00:00.000Z',
        '2024-01-01T00:00:00Z','2024-01-01T00:00:00.1Z','2024-01-01T00:00:00.12Z',
        '2024-01-01T00:00:00.1234Z','2024-01-01T00:00:00+00:00','2024-01-01T00:00:00-00:00',
        '2024-01-01T00:00:00+24:00','2024-01-01T00:00:00+01:60',
        '2024-01-01T00:00:00+05:45','2024-01-01T00:00:00-03:30',
        '0001-01-01T00:00:00+23:59','9999-12-31T23:59:59.999-23:59',
        '2024-01-01t00:00:00.000z','２０２４-01-01T00:00:00.000Z',None,False]
    instants.extend('2024-01-01T00:00:00.000Z'+suffix for suffix in ['\n','\r','\r\n','\u2028','\u2029','\n\n'])
    for value in instants:
        for op in ['parseOffsetInstant','fourDigitYearEpoch']:add(op,value)
    for date,time in [('2000-02-29','12:00:00'),('1900-02-29','12:00:00'),('0000-01-01','00:00:00'),
            ('9999-12-31','23:59:59.999'),('2024-02-30','24:00:00'),('2024-13-01','00:00:00'),
            ('2024-01-01','00:00:00.1'),('2024-01-01','00:00:00.12'),('2024-01-01','00:00:00.1234'),
            ('2024-01-01\r\n','00:00:00\u2028'),(None,True)]:add('parseLocalCalendar',date,time)
    for value in [-62135596800000,-62135596800001,253402300799999,253402300800000,0,0.5,True,None,'0',1e100]:
        add('formatFourDigitYearInstant',value);add('isFourDigitYearInstant',value)
    for zone in ['',' UTC','UTC ','utc','UTC','Asia/Shanghai','asia/shanghai','US/Eastern','Asia/Calcutta',
            'Europe/Kiev','Etc/UTC','Etc/GMT+5','GMT','+08:00','Unknown/Zone','America/New_York\n']:
        add('canonicalizeTimeZone',zone)
    for date,time,zone in [
            ('2024-03-10','02:30:00','America/New_York'),('2024-11-03','01:30:00','America/New_York'),
            ('2024-04-07','01:45:00','Australia/Lord_Howe'),('2024-10-06','02:15:00','Australia/Lord_Howe'),
            ('2011-12-30','12:00:00','Pacific/Apia'),('1900-01-01','00:00:00','Europe/Paris'),
            ('0001-01-01','00:00:00','UTC'),('0001-01-01','00:00:00','Asia/Shanghai'),
            ('9999-12-31','23:59:59.999','UTC'),('9999-12-31','23:59:59.999','America/New_York'),
            ('2024-02-29','12:00:00','Asia/Kathmandu')]:
        add('resolve',date,time,zone)
    for year in [0,-1,10000,10004]:
        for zone in ['UTC','Asia/Shanghai','America/New_York']:
            add('resolveParts',dict(year=year,month=2,day=28,hour=12,minute=0,second=0,millisecond=0),zone)
    for parts,zone in [(dict(year=2024,month=2,day=30,hour=0,minute=0,second=0,millisecond=0),'UTC'),
            (dict(year=2024,month=1,day=1,hour=0,minute=0,second=0,millisecond=0),'Unknown/Zone')]:
        add('resolveParts',parts,zone)
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh import util_time_instant as instant
    rows=[]
    for case in cases():
        op,args=case['op'],case['args']
        try:
            if op=='resolve':result=instant.resolve_local_instant(instant.parse_local_calendar(*args[:2])['time'],args[2])
            elif op=='resolveParts':result=instant.resolve_local_instant(*args)
            else:result=getattr(instant,op)(*args)
        except Exception as error:
            rows.append(dict(op=op,args=args,error=getattr(error,'name',type(error).__name__)));continue
        if isinstance(result,dict) and 'cause' in result:
            result=dict(result,cause=dict(name=result['cause'].name,message=str(result['cause'])))
        rows.append(dict(op=op,args=args,value=result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_time_instant.mts',prepare=prepare,
        scope='Actual strict instant/calendar parsing, four-digit bounds, pinned Intl zone identity, Temporal gap/overlap and local year-boundary resolution; exact values/reasons and unsupported-zone error cause.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/util_time_instant.py',ROOT/'dsh/util_time.py',ROOT/'dsh/resources/time_zones_current.json'])
