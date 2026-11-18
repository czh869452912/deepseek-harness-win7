"""Current Queue/Steer Remote controls and pinned Intl wire-zone vocabulary."""
import json
from pathlib import Path

import pytest

from dsh.util_time import canonical_client_time_zone
from scripts.oracles.agent_machine_current_python import execute
from scripts.oracles.session_format_python import decode

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'scripts/oracles/subagent_remote_current_cases.json').read_text(encoding='utf-8'))
JOURNEYS, ZONES = CASES[:-1], CASES[-1]


@pytest.mark.parametrize('case', JOURNEYS, ids=lambda case: case['case'])
def test_retained_v3_subagent_remote(case):
    result = execute(case, decode)
    assert result == case['expected']
    if case['case'].endswith(('actual-queue', 'actual-steer')):
        rows = result['results']
        assert rows[1]['outcome'] == 'value'
        assert rows[4]['outcome'] == 'value' and rows[4]['value']['messageId']
        assert any(event['type'] == 'user/message' and event['data']['source'].get('clientTimeZone') == 'Asia/Shanghai'
                   for event in rows[6]['value']['events'])
        assert rows[7]['value'] == dict(accepted=True)
        assert rows[8]['value'] == dict(accepted=True)
    if case['case'].endswith('running-authorization'):
        assert result['results'][3]['error']['code'] == 'subagent/unauthorized'
        assert result['results'][4]['value'] == dict(accepted=True)


@pytest.mark.parametrize('action,expected', zip(ZONES['actions'], ZONES['expected']['results']),
                         ids=[action['value'] for action in ZONES['actions']])
def test_pinned_original_intl_wire_zones(action, expected):
    assert expected['outcome'] == 'value'
    assert canonical_client_time_zone(action['value']) == expected['value']
