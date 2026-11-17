"""Pinned RRULE pure UTC enumeration on the shipped Win7 worker versus Source."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    for recurrence in [
            'FREQ=MINUTELY;INTERVAL=7','FREQ=HOURLY;INTERVAL=3','FREQ=DAILY;BYHOUR=1,12;BYMINUTE=0,30;BYSECOND=0',
            'FREQ=WEEKLY;WKST=SU;BYDAY=MO,WE,FR','FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1',
            'FREQ=MONTHLY;BYMONTHDAY=31','FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29',
            'FREQ=YEARLY;BYWEEKNO=1,-1;BYDAY=MO','FREQ=YEARLY;BYYEARDAY=-1',
            'FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30']:
        for anchor in [1704067200000,-59011459200000,253370764800000]:
            rows.append(dict(recurrence='RRULE:'+recurrence,anchor=anchor,from_wall=anchor,through=anchor+2*86400000,limit=10,mode='window'))
            rows.append(dict(recurrence='RRULE:'+recurrence,anchor=anchor,from_wall=anchor+60000,mode='after'))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.javascript.rrule_enumerator import enumerate_wall
    return [enumerate_wall(**case) for case in cases()]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_rrule_enumerator.mts',prepare=prepare,
        scope='Actual rrule@2.8.1 UTC-shaped enumeration against byte-preserved package on Win7 worker: six frequencies, BYDAY/BYSETPOS/BYWEEKNO/BYYEARDAY, impossible dates, year100 and late-year anchors, bounded pages and after queries.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/javascript/rrule_enumerator.py',ROOT/'dsh/javascript/rrule/manifest.json',ROOT/'dsh/javascript/rrule/rrule.min.js',ROOT/'dsh/javascript/rrule/driver.js'])
