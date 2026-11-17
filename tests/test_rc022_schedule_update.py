import json

import pytest

from dsh.schedule import domain_current as domain,update_current as update
from scripts.rc022_schedule_update_probe import observe,TIMINGS,NOW


@pytest.mark.asyncio
async def test_seven_rule_construction_and_edit_observations(tmp_path):
    rows=await observe()
    (tmp_path/'schedule-update-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len([row for row in rows if row['op']=='decodeJourney' and row['value']['same'] is False])==7
    equivalent=[row['value'] for row in rows if row['op']=='editJourney' and row['args'][2]==NOW+864000000]
    assert len(equivalent)==3 and all(value['same'] for value in equivalent)
    assert rows[-1]['value']=='+010000-01-01T13:59:59+14:00'


def test_edit_preserves_targets_and_nested_weekday_identity():
    current=update.create_schedule_record('id','title','prompt',TIMINGS[4],NOW)
    assert update.update_schedule_record(current,{},NOW+864000000,False) is current
    revised=update.update_schedule_record(current,dict(title='new'),NOW+864000000,False)
    assert revised['weekdays'] is current['weekdays']
    assert revised['scheduledAt']==current['scheduledAt']
    assert domain.decode_schedule_record(current)['weekdays'] is not current['weekdays']
    rearmed=update.update_schedule_record(current,{},NOW+864000000,True)
    assert rearmed['scheduledAt']>current['scheduledAt']


def test_resume_expired_one_shot_requires_a_new_future_schedule():
    current=update.create_schedule_record('id','title','prompt',TIMINGS[0],NOW)
    with pytest.raises(domain.ScheduleInputError,match='Set a future schedule') as caught:
        update.update_schedule_record(current,{},NOW+60001,True)
    assert caught.value.code=='not_future'
