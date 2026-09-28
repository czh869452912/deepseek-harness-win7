import pytest
from dsh.context.time_context.request_zone import browser_time_zone
from dsh.context.time_context.timestamp import format_timestamp
from dsh.schedule.domain import canonicalize_time_zone, ScheduleInputError


def test_browser_and_schedule_validate_iana_zones_on_python38():
    for zone in ('UTC', 'Asia/Shanghai', 'America/New_York'):
        assert browser_time_zone({'source': {'kind': 'user', 'rpcId': 'test', 'clientTimeZone': zone}}) == zone
        assert canonicalize_time_zone(zone) == zone
    with pytest.raises(TypeError):
        browser_time_zone({'source': {'kind': 'user', 'rpcId': 'test', 'clientTimeZone': 'Invalid/Place'}})
    with pytest.raises(ScheduleInputError):
        canonicalize_time_zone('Invalid/Place')


def test_timestamp_uses_requested_zone_and_daylight_saving():
    assert format_timestamp(0, 'Asia/Shanghai') == '1970-01-01T08:00:00+08:00[Asia/Shanghai]'
    assert format_timestamp(0, 'UTC') == '1970-01-01T00:00:00+00:00[UTC]'
    assert '-04:00[America/New_York]' in format_timestamp(1751371200000, 'America/New_York')
