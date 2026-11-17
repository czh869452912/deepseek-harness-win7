import json

import pytest

from scripts import rc022_mcp_cache_probe as corpus
from scripts import rc022_mcp_server_probe_probe as peer
from dsh.mcp.client_current import CurrentSdkClient
from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport


@pytest.mark.asyncio
async def test_default_cache_matches_original_observed_request_counts_and_race_rules():
    rows=await corpus.observe()
    assert [len(row['requests']) for row in rows]==[4,4,4,4,4,2,2,6,3,4,6,2,5,4,3,5]
    for row in rows[:4]:
        assert row['rows'][0]==row['rows'][1]
        assert row['rows'][1]==row['rows'][3]
        assert row['rows'][4]==row['rows'][5]
    assert rows[9]['requests'][1]['params']==dict(_meta=dict(trace='owned'),cursor='1')
    assert rows[10]['rows'][0]!=rows[10]['rows'][1]
    assert rows[10]['rows'][1]==rows[10]['rows'][2]
    assert rows[11]['rows'][0]!=rows[11]['rows'][1]
    assert rows[12]['rows'][0]['error']['message']=='scripted page failure'
    assert rows[13]['rows'][0]['error']['code']=='LIST_PAGINATION_EXCEEDED'


@pytest.mark.asyncio
async def test_real_modern_http_ttl_refresh_invalidation_and_owned_close(tmp_path):
    peer.prepare(tmp_path)
    client=CurrentSdkClient()
    wire=CurrentStreamableHttpMcpTransport(peer.URL+'/modern-cache')
    def calls():
        return sum(json.loads(line)['packet']['method']=='tools/list'
            for line in peer.LOG.read_text(encoding='utf-8').splitlines())
    try:
        await client.connect(wire)
        first=await client.listTools()
        assert [tool['name'] for tool in first['tools']]==['a','b','c'] and calls()==2
        first['tools'].clear()
        assert len((await client.listTools())['tools'])==3 and calls()==2
        await client.listTools(options=dict(cacheMode='refresh'))
        assert calls()==4
        await client.listTools(options=dict(cacheMode='bypass'))
        assert calls()==6
        await client.listTools()
        assert calls()==6
        client._notification(dict(method='notifications/tools/list_changed'))
        await client.listTools()
        assert calls()==8
        await client.close()
        assert client._cache.entries=={} and client._cache.generations=={}
    finally:
        await client.close()
        peer.stop_peer()
