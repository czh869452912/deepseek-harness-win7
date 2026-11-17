import json

import pytest

from dsh.schedule import domain_current as domain
from scripts.rc022_schedule_interval_probe import observe,NOW


@pytest.mark.asyncio
async def test_current_interval_observations_and_fixed_rate_floor(tmp_path):
    rows=await observe()
    (tmp_path/'schedule-interval-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    record=domain.create_every_schedule_record('id',' prompt ',60,NOW,' title ')
    assert record['title']=='title' and record['scheduledAt']=='2024-01-01T00:01:00.000Z'
    result=domain.resolve_every_occurrence(record,NOW+3600000000)
    assert result==dict(occurrenceAt='2024-02-11T16:00:00.000Z',nextScheduledAt='2024-02-11T16:01:00.000Z')
    with pytest.raises(TypeError):record['title']='changed'
    detached=domain.decode_interval_record(dict(record))
    assert detached==record and detached is not record
    with pytest.raises(TypeError):detached['scheduledAt']='changed'


def test_exhaustion_and_failed_admission_do_not_change_committed_record():
    record=domain.create_every_schedule_record('id','prompt',60,253402300739999,'title')
    assert domain.resolve_every_occurrence(record,253402300799999)==dict(occurrenceAt='9999-12-31T23:59:59.999Z')
    before=dict(record)
    with pytest.raises(domain.ScheduleLogError):domain.resolve_every_occurrence(record,253402300799998)
    assert record==before
