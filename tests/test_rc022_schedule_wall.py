import json

import pytest

from dsh.schedule import domain_current as domain
from scripts.rc022_schedule_wall_probe import observe


@pytest.mark.asyncio
async def test_wall_calendar_observations_and_weekday_freezing(tmp_path):
    rows=await observe()
    (tmp_path/'schedule-wall-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    journeys=[row for row in rows if row['op']=='journey']
    assert len(journeys)==16 and all('value' in row for row in journeys)
    assert journeys[1]['value']==dict(occurrenceAt='2024-03-11T06:30:00.000Z',nextScheduledAt='2024-03-12T06:30:00.000Z')
    assert journeys[2]['value']==dict(occurrenceAt='2024-11-03T05:30:00.000Z',nextScheduledAt='2024-11-04T06:30:00.000Z')
    assert journeys[7]['value']==dict(occurrenceAt='9999-12-31T10:00:00.000Z')
    record=domain.create_weekly_schedule_record('id','prompt',dict(time='12:00:00',time_zone='UTC',weekdays=[7,1]),1704067200000,'title')
    assert record['weekdays']==[1,7]
    with pytest.raises(TypeError):record['weekdays'].append(2)
    decoded=domain.decode_wall_record(record)
    assert decoded is not record and decoded['weekdays'] is not record['weekdays']


def test_committed_wall_target_is_not_recomputed_on_read():
    record=dict(id='id',kind='daily',title='title',prompt='prompt',time='12:00:00.000',timeZone='UTC',scheduledAt='2024-01-01T00:00:00.000Z')
    assert domain.decode_wall_record(record)['scheduledAt']==record['scheduledAt']
    # A saved occurrence remains due when current zone rules put the rule before it.
    assert domain.resolve_daily_occurrence(record,1704067200000)['occurrenceAt']==record['scheduledAt']
