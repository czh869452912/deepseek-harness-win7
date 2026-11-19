import asyncio

import pytest

from dsh.core.abort import AbortController
from dsh.mcp.client_current import CurrentSdkClient
from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
from dsh.mcp.negotiation_current import SdkError
from dsh.mcp.request_current import delay_seconds
from scripts import rc022_mcp_request_probe as corpus


@pytest.mark.asyncio
async def test_actual_http_sse_deadlines_aborts_server_errors_and_owned_disconnect(tmp_path):
    corpus.prepare(tmp_path)
    try:
        rows=await corpus.observe()
        assert len(rows)==50
        for start in (0,25):
            group=rows[start:start+25]
            assert group[0]['result']['error']==dict(name='SdkError',message='Request timed out',code='REQUEST_TIMEOUT',data=dict(timeout=50))
            assert len(group[1]['progress'])==1
            assert len(group[2]['progress'])==3 and 'value' in group[2]['result']
            assert group[3]['result']['error']['data']==dict(maxTotalTimeout=250,totalElapsed=300)
            assert 'value' in group[4]['result']
            assert group[5]['result']['error']==dict(name='ProtocolError',message='serve-failed',code=-32602)
            assert group[6]['result']['error']['data'] is None
            assert group[7]['result']['error']['data']==dict(detail='retained')
            for row in group[8:24]:
                assert row['result']['reasonIdentity']==(row['case']['abort']=='sdk')
                if row['case'].get('pre'):assert row['packets']==[]
            assert group[24]['result']['error']['code']=='CONNECTION_CLOSED'
        assert all(row['listeners']==0 for row in rows)
        assert all(packet['method']!='notifications/cancelled' for row in rows[25:] for packet in row['packets'])
    finally:corpus.stop_peer()


@pytest.mark.asyncio
async def test_cancelled_modern_http_stream_does_not_cancel_overlapping_sibling(tmp_path):
    corpus.prepare(tmp_path);client=CurrentSdkClient();controller=AbortController()
    wire=CurrentStreamableHttpMcpTransport(corpus.URL+'/native/overlap/modern-overlap')
    slow=None
    try:
        await client.connect(wire)
        slow=asyncio.create_task(client.request(dict(method='tools/list',params=dict(hold=True)),dict(signal=controller.signal,timeout=2000)))
        for _ in range(1000):
            if any(row['packet']['method']=='tools/list' for row in corpus.records()):break
            await asyncio.sleep(.002)
        else:raise AssertionError('slow stream not observed')
        fast=asyncio.create_task(client.request(dict(method='tools/list'),dict(timeout=1000)))
        controller.abort('slow-only')
        with pytest.raises(SdkError,match='slow-only'):await slow
        assert (await asyncio.wait_for(fast,1))['tools']==[]
        assert not wire._pending and not wire._sdk_requests and controller.signal._listeners==[]
    finally:
        await client.close()
        if slow is not None:await asyncio.gather(slow,return_exceptions=True)
        corpus.stop_peer()
    assert not wire._writers and not wire._request_sends


@pytest.mark.parametrize('value,seconds',[(0,.001),(-1,.001),(2147483648,.001),(float('nan'),.001),(1.9,.001),(1000,1)])
def test_node_timer_duration_bounds(value,seconds):
    assert delay_seconds(value)==seconds


@pytest.mark.asyncio
@pytest.mark.parametrize('delay', [0, .12])
async def test_legacy_cancel_observation_waits_for_actual_peer_before_close(tmp_path, monkeypatch, delay):
    case=corpus.cases()[12]
    monkeypatch.setattr(corpus,'cases',lambda:[case])
    original=CurrentStreamableHttpMcpTransport._cancel_request
    async def delayed(self,params):
        await asyncio.sleep(delay)
        await original(self,params)
    monkeypatch.setattr(CurrentStreamableHttpMcpTransport,'_cancel_request',delayed)
    corpus.prepare(tmp_path)
    try:
        rows=await corpus.observe()
    finally:corpus.stop_peer()
    assert len(rows)==1
    row=rows[0]
    assert row['packets']==[
        dict(method='tools/list',jsonrpc='2.0',id=1),
        dict(jsonrpc='2.0',method='notifications/cancelled',params=dict(requestId=1,reason='[object Object]'))]
    assert row['result']==dict(error=dict(name='SdkError',message='[object Object]',code='REQUEST_TIMEOUT'),reasonIdentity=False)
    assert row['listeners']==0
