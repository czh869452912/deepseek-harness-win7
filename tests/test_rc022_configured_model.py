import pytest
from scripts.rc022_configured_model_probe import observe


@pytest.mark.asyncio
async def test_configured_cold_resume_applies_route_before_publication(tmp_path):
    rows = await observe(tmp_path)
    previous = dict(provider='p', model='m', reasoningEffort='high')
    for row in rows:
        action = row['action']
        if action == 'fresh' and row['explicit']:
            assert row == dict(action=action, explicit=True, error='not-found')
            continue
        expected = (dict(provider='p', model='other') if action == 'changed' else
                    dict(provider='p', model='m', reasoningEffort='low') if action == 'explicit' else
                    dict(provider='p', model='m') if action == 'fresh' else previous)
        assert row['published'] == expected
        assert row['events'] == ([] if action == 'fresh' else
                                  [previous, expected] if action in ('changed', 'explicit') else [previous])
