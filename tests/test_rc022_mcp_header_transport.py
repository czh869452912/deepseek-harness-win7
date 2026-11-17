from types import SimpleNamespace

import pytest

from dsh.mcp.client_current import CurrentSdkClient
from scripts import rc022_mcp_header_transport_probe as corpus


@pytest.mark.asyncio
async def test_actual_http_filtering_mirroring_reserved_headers_and_single_recovery(tmp_path):
    corpus.prepare(tmp_path)
    try:
        rows=await corpus.observe()
        assert len(rows)==16
        first=rows[0]
        assert first['tools']==['probe']
        assert [row['packet']['method'] for row in first['wire']]==['tools/list','tools/call','tools/list','tools/call']
        assert first['wire'][1]['headers']['mcp-param-trace']=='=?base64?5Lit5paH?='
        assert first['wire'][3]['headers']['mcp-param-next']=='=?base64?5Lit5paH?='
        for row in first['wire']:
            assert row['headers']['authorization']=='Bearer owned'
            assert row['headers']['mcp-protocol-version']=='2026-07-28'
            assert row['headers']['mcp-method']==row['packet']['method']
            assert row['headers']['content-type']=='application/json'
        assert first['wire'][2]['headers'].get('x-extra') is None
        assert rows[1]['result']['error']['code']==-32020 and len(rows[1]['wire'])==4
        assert rows[2]['errors']==[dict(name='ProtocolError',message='refresh failed',code=-32603)]
        assert 'mcp-param-next' not in rows[2]['wire'][-1]['headers']
        assert rows[3]['tools']==['probe','invalid'] and len(rows[3]['wire'])==2
        assert rows[4]['result']['value']['structuredContent']==dict(answer='accepted')
        assert rows[5]['result']['error']['code']==-32602 and len(rows[5]['wire'])==3
        assert rows[-2]['result']['error']['code']==-32020 and len(rows[-2]['wire'])==2
        assert rows[-2]['wire'][1]['headers']['mcp-param-override']=='value'
        assert rows[-1]['tools']==['probe'] and 'mcp-param-trace' not in rows[-1]['wire'][1]['headers']
    finally:corpus.peer.stop_peer()


@pytest.mark.parametrize('era,kind,filtered',[('modern','stdio',False),('legacy','streamable-http',False),('modern','streamable-http',True)])
def test_invalid_declaration_filter_is_scoped_to_modern_http(era,kind,filtered):
    client=CurrentSdkClient();client.transport=SimpleNamespace(negotiated=dict(era=era),transport_kind=kind)
    result=client._filter_tools(dict(tools=[dict(name='invalid',inputSchema={'x-mcp-header':'Root','type':'string'})]))
    assert result['tools']==([] if filtered else [dict(name='invalid',inputSchema={'x-mcp-header':'Root','type':'string'})])
