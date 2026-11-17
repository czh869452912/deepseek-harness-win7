import asyncio
import json

import pytest

from dsh.mcp.client_current import CurrentSdkClient
from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
from dsh.mcp.negotiation_current import SdkError
from scripts import rc022_mcp_flow_budget_probe as corpus
from scripts import rc022_mcp_server_probe_probe as peer


@pytest.mark.asyncio
async def test_original_flow_budget_boundaries_and_retry_ownership():
    rows=await corpus.observe()
    assert len(rows)==13
    assert all(row['result']['error']['code']=='REQUEST_TIMEOUT' and row['retries']==[] for row in rows[:5])
    assert rows[4]['result']['error']['data']==dict(maxTotalTimeout=350,totalElapsed=350)
    assert rows[5]['retries'][0]['options']==dict(allowInputRequired=True,maxTotalTimeout=1)
    assert rows[8]['result']['error']['data']==dict(maxTotalTimeout=900,totalElapsed=910)
    assert 'value' in rows[9]['result']
    assert rows[10]['result']['error']['code']=='INPUT_REQUIRED_ROUNDS_EXCEEDED'
    retries=rows[11]['retries']
    assert [row['options']['maxTotalTimeout'] for row in retries]==[640,370]
    assert all(row['options']['timeout']==123 and row['options']['allowInputRequired'] for row in retries)
    assert all('relatedRequestId' not in row['options'] and 'resumptionToken' not in row['options'] for row in retries)
    assert all('maxTotalTimeout' not in row['options'] for row in rows[12]['retries'])


@pytest.mark.asyncio
async def test_actual_http_state_pacing_exhausts_total_budget_before_second_leg(tmp_path):
    peer.prepare(tmp_path)
    client=CurrentSdkClient();wire=CurrentStreamableHttpMcpTransport(peer.URL+'/modern-input-state')
    try:
        await client.connect(wire)
        with pytest.raises(SdkError,match='Maximum total timeout exceeded') as caught:
            await asyncio.wait_for(client.listTools(options=dict(timeout=1000,maxTotalTimeout=100)),2)
        assert caught.value.code=='REQUEST_TIMEOUT'
        assert caught.value.data['maxTotalTimeout']==100 and caught.value.data['totalElapsed']>=250
        packets=[json.loads(line)['packet'] for line in peer.LOG.read_text(encoding='utf-8').splitlines()]
        assert sum(packet['method']=='tools/list' for packet in packets)==1
        assert not wire._pending
    finally:
        await client.close();peer.stop_peer()
