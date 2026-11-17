import json

import pytest

from dsh import util_time_instant as instant
from scripts.rc022_time_instant_probe import observe


@pytest.mark.asyncio
async def test_instant_boundary_observations(tmp_path):
    rows=await observe()
    (tmp_path/'time-instant-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    resolved=[row['value'] for row in rows if row['op']=='resolve']
    assert resolved[:5]==[None,1730611800000,1712414700000,None,None]
    assert resolved[6:10]==[-62135596800000,-62135625943000,253402300799999,253402318799999]
    assert instant.four_digit_year_epoch('0001-01-01T00:00:00.000Z')['epoch']==instant.MIN_FOUR_DIGIT_YEAR_MS
    assert instant.format_four_digit_year_instant(instant.MAX_FOUR_DIGIT_YEAR_MS)=='9999-12-31T23:59:59.999Z'


@pytest.mark.parametrize('epoch',[float('nan'),float('inf'),-float('inf'),10**1000,[],{}])
def test_unrepresentable_epoch_never_formats_or_throws(epoch):
    assert instant.format_four_digit_year_instant(epoch) is None
    assert not instant.is_four_digit_year_instant(epoch)
