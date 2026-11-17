import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.util_time_rrule import RRule
from scripts.rc022_time_rrule_probe import observe,rule,epoch


@pytest.mark.asyncio
async def test_bounded_rrule_observations(tmp_path):
    rows=await observe()
    (tmp_path/'time-rrule-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    journeys=[row['value'] for row in rows if row['op']=='journey']
    assert len(journeys)==9
    assert journeys[0]['decision']==dict(occurrenceAt='2026-03-07T07:30:00.000Z',nextScheduledAt='2026-03-09T06:30:00.000Z')
    assert journeys[1]['decision']==dict(occurrenceAt='2026-03-10T06:30:00.000Z')
    assert journeys[3]['decision']==dict(occurrenceAt='2026-11-01T05:45:00.000Z',nextScheduledAt='2026-11-01T07:00:00.000Z')
    assert journeys[4]['decision']==dict(occurrenceAt='2026-01-21T03:00:00.000Z',nextScheduledAt='2026-01-28T03:00:00.000Z')
    assert journeys[5]['decision']==dict(occurrenceAt='2026-09-17T01:00:00.000Z')
    assert journeys[6]['decision']==dict(occurrenceAt='2044-02-29T00:00:00.000Z',nextScheduledAt='2072-02-29T00:00:00.000Z')
    assert journeys[-1]['decision']==dict(occurrenceAt='9999-12-31T04:00:00.000Z')


def test_same_immutable_rule_can_serve_repeated_decisions_and_preserve_committed_floor():
    current=RRule.parse(rule('FREQ=DAILY'))['rule']
    with pytest.raises(TypeError):current.timeZone='other'
    saved='2026-09-16T00:30:00.000Z';at=epoch('2026-09-16T00:45:00Z')
    expected=dict(occurrenceAt=saved,nextScheduledAt='2026-09-16T01:00:00.000Z')
    assert current.resolve(saved,at)==expected
    assert current.resolve(saved,at)==expected


def test_x86_rrule_dst_count_decision(tmp_path):
    binary=os.environ.get('DSH_TEST_X86_PYTHON')
    if not binary:pytest.skip('x86 Python not configured')
    root=Path(__file__).resolve().parents[1]
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from dsh.util_time_rrule import RRule;r=RRule.parse('DTSTART;TZID=America/New_York:20260307T023000\\nRRULE:FREQ=DAILY;COUNT=3')['rule'];print(json.dumps(r.resolve('2026-03-07T07:30:00.000Z',1772971200000)))"
    result=subprocess.run([binary,'-c',code,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    (tmp_path/'x86-time-rrule-observations.json').write_text(json.dumps(dict(exit_code=result.returncode,stdout=result.stdout.decode('utf-8'),stderr=result.stderr.decode('utf-8'))),encoding='utf-8')
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==dict(occurrenceAt='2026-03-07T07:30:00.000Z',nextScheduledAt='2026-03-09T06:30:00.000Z')
