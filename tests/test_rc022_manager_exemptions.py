import pytest
from scripts.rc022_manager_exemptions_probe import observe


@pytest.mark.asyncio
async def test_exact_exemptions_admit_and_remove_real_runtime_rows(tmp_path):
    rows = {row['name']:row for row in await observe(tmp_path)}
    assert len(rows) == 12
    live = rows['live']['steps']
    assert not live[0]['active'] and live[0]['result']['application'] == 'failed'
    assert live[1]['active'] and live[1]['result']['changed']
    assert live[1]['listing'] == dict(exemptions={'extra@1.0.0':['0.2.2-rc.3']}, warnings=0)
    assert live[2]['active'] and not live[2]['result']['changed']
    assert not live[3]['active'] and live[3]['listing']['exemptions'] == {}
    assert all(step['selection'] == ['core', 'extra'] for row in rows.values() for step in row['steps'])
    assert not rows['startup']['steps'][1]['active']
    assert rows['startup']['steps'][1]['result']['application'] == 'restart-required'
    assert rows['reload-failure']['steps'][1]['result']['changed']
    assert rows['reload-failure']['steps'][1]['result']['application'] == 'failed'
    assert all(not step['result']['changed'] and step['listing']['warnings'] == 1 for step in rows['damaged']['steps'])
    for mode in ('range', 'whitespace', 'credential', 'runtime-range', 'alias'):
        assert all(fact['target'] is None and 'version' not in fact for fact in rows[mode]['facts'])
        assert all(not step['result']['changed'] for step in rows[mode]['steps'])
    assert all(fact['target'] == '@scope/extra' and fact['version'] == '2.0.0' for fact in rows['scoped']['facts'])
    assert rows['old-runtime']['steps'][0]['result']['application'] == 'failed'
    assert rows['old-runtime']['steps'][1]['result']['application'] == 'applied'
    assert rows['boolean-risk']['steps'][0]['result']['application'] == 'failed'
