import json

import pytest

from dsh.util_time_cron import Cron
from scripts.rc022_schedule_cron_probe import observe


@pytest.mark.asyncio
async def test_cron_observations_and_star_semantics(tmp_path):
    rows=await observe()
    (tmp_path/'schedule-cron-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    journeys=[row['value'] for row in rows if row['op']=='journey']
    assert journeys[0]['decision']['occurrenceAt']=='2026-11-01T05:45:00.000Z'
    assert journeys[2]['decision']['occurrenceAt']=='2026-01-01T10:30:00.000Z'
    assert journeys[5]['decision']['occurrenceAt']=='2024-01-29T00:00:00.000Z'
    assert journeys[6]['decision']['occurrenceAt']=='2024-02-01T00:00:00.000Z'
    rule=Cron.parse('0 0 */2 * 1','UTC')['rule']
    assert rule.fields['dayOfMonthStar'] and not rule.fields['dayOfWeekStar']
    with pytest.raises(TypeError):rule.fields['minutes'].append(5)
    with pytest.raises(TypeError):rule.timeZone='other'


def test_impossible_calendar_terminates_and_decode_does_not_rearm():
    rule=Cron.parse('0 0 30 2 *','UTC')['rule']
    assert rule.next(1704067200000) is None
    assert rule.resolve('2024-01-01T00:00:00.000Z',1704067200000)==dict(occurrenceAt='2024-01-01T00:00:00.000Z')
