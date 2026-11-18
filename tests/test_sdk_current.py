"""Retained pre-v4 SDK journeys; current acceptance uses the rc022 SDK probes."""
import json
from pathlib import Path

import pytest

from scripts.oracles.agent_machine_current_python import execute
from scripts.oracles.session_format_python import decode

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'scripts/oracles/sdk_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_retained_sdk_business_api_with_legacy_machine(case):
    result=execute(case,decode)
    assert result==case['expected']
    if case['case'].startswith('sdk-current-'):
        assert result['results'][1]['outcome']=='value'
        assert result['results'][1]['value']['serverInfo']['name']=='deepseek-harness-sdk-runtime'
    if case['case']=='sdk-current-external-child':
        assert result['results'][3]['outcome']=='value'
        assert result['results'][3]['value']['result']['stopReason']=='completed'
        assert not any(row['name']=='subagent.finished' for row in result['notifications'])
    if case['case']=='sdk-current-local-child':
        finished=[row['payload'] for row in result['notifications'] if row['name']=='subagent.finished']
        assert len(finished)==1 and finished[0]['parentSessionId']=='machine' and finished[0]['status']=='ok'
