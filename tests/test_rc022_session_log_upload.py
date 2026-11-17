"""Regression for missing default uploads and bounded, reversible admission."""
import pytest
from scripts.rc022_session_log_upload_probe import observe


@pytest.mark.asyncio
async def test_mounted_upload_defaults_limits_live_config_and_unload():
    rows = {row['case']: row for row in await observe()}
    payload = rows['default']['results'][0]['dsh_session_log']
    assert payload['sessionFormatVersion'] == 4
    assert payload['throughSeq'] == 1 and len(payload['events']) == 2
    assert rows['disabled']['results'] == [{}, {}]
    assert rows['toggle']['results'][0] == {}
    assert rows['toggle']['results'][1]['dsh_session_log']['throughSeq'] == 1
    assert rows['exclude']['results'][0] == {} and rows['exclude']['results'][1]
    assert rows['purpose']['uploads'] == [dict(sessionId='upload', purpose='title')]
    assert rows['throw']['results'][0] == {} and len(rows['throw']['warnings']) == 1
    assert rows['blocked']['results'] == rows['below']['results'] == [{}, {}]
    assert len(rows['blocked']['warnings']) == len(rows['below']['warnings']) == 1
    assert rows['exact']['results'][0]['dsh_session_log']['throughSeq'] == 0
    prefix = rows['prefix']['results'][1]['dsh_session_log']
    assert prefix['afterSeq'] == 0 and prefix['events'][0]['seq'] == 1
    assert rows['unload']['mounted'] is False and rows['unload']['results'][1] == {}
    assert rows['owner']['results'][0] == {} and rows['owner']['results'][1]
