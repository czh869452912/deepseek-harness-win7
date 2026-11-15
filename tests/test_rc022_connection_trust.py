import pytest
from dsh.host.connection.trust_current import is_trusted_api_request as trusted
from scripts.rc022_connection_trust_probe import observe


@pytest.mark.asyncio
async def test_observed_authority_matrix_and_listener_literals():
    rows=await observe()
    assert len(rows)==174
    assert all(row['allowed'] for row in rows[160:163])
    assert rows[-6:]==[dict(authority=value,remote=remote) for value,remote in [('localhost',False),('127.1',False),('[::1]',False),('remote.example',True),('10.1.2.3',True),('invalid:port',True)]]


@pytest.mark.parametrize('protocol,host,origin,expected',[
    ('https:','remote.example:443','https://remote.example',True),
    ('https:','remote.example:80','https://remote.example',False),
    ('http:','remote.example:443','https://remote.example',True),
    ('http:','remote.example:80','https://remote.example',False),
    ('http:','remote.example:80','http://remote.example',True),
])
def test_listener_and_origin_default_ports_are_independent(protocol,host,origin,expected):
    assert trusted(dict(headers=dict(host=host,origin=origin)),['remote.example'],protocol=protocol) is expected
