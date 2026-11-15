import pytest
from scripts.rc022_sandbox_escalation_probe import observe


@pytest.mark.asyncio
async def test_current_escalation_typed_outcomes_locales_and_abort_identity():
    rows=await observe();assert len(rows)==30
    assert rows[1]['code']=='SANDBOX_ESCALATION_INVALID_ARGUMENT'
    assert rows[3]['code']=='SANDBOX_ESCALATION_INVALID_ARGUMENT' and rows[4]['value']=='valid'
    cases={row['name']:row for row in rows[5:]}
    grant=cases['read-only>workspace-write/allowed-once/both']
    assert len(grant['asked'])==1 and grant['value']=='workspace-write'
    reason=grant['asked'][0];assert reason['agent'] and reason['signal']
    assert set(reason['displayReason'])=={'en','zh','ja','es','fr','de','ru','pt'}
    assert all('需要写入 "输出"\nverbatim' in text for text in reason['displayReason'].values())
    assert cases['read-only>workspace-write/rejected/both']['code']=='SANDBOX_ESCALATION_REJECTED'
    assert cases['read-only>workspace-write/cancelled/both']['code']=='SANDBOX_ESCALATION_CANCELLED'
    assert cases['read-only>workspace-write/allowed-once/no-agent']['asked']==[]
    assert cases['workspace-write>workspace-write/allowed-once/no-service']['value']=='workspace-write'
    assert cases['workspace-write>read-only/allowed-once/both']['asked']==[]
    assert cases['read-only>workspace-write/cancelled/aborted']['originalError']
