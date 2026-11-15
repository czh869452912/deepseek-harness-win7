import pytest
from scripts.rc022_connection_plugin_probe import observe


@pytest.mark.asyncio
async def test_actual_plugin_http_middleware_and_reload():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==8
    assert rows['headless']==dict(name='headless',available=True,web=False)
    assert rows['rpc']['trace']==['before','handler','after']
    assert rows['rpc']['body']['result']['value']['interactions']=='none'
    assert rows['unauthenticated']['trace']==[]
    assert rows['blocked']==dict(name='blocked',status=503,body='paused',trace=['before','refused'])
    assert rows['unloaded']==dict(name='unloaded',connection=False,connect=False,api=False,injections=[],browserAborted=True)
    assert rows['reloaded']==dict(name='reloaded',sameToken=True,sameSecret=True,modifies=2,records=1)
