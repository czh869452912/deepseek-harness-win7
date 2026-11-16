import asyncio
import pytest

from dsh.mcp.manager_entries_current import MANAGER_CONFIG, validate_entries, to_client_config
from scripts.rc022_mcp_manager_entries_probe import observe


def test_manager_write_contract_corpus():
    rows=asyncio.run(observe())
    assert len(rows)==56
    assert rows[0]['result']['client']['expandTemplates'] is True
    assert rows[0]['result']['client']['startupTimeoutMs']==30000
    assert 'requires "command"' in rows[5]['result']['error']['message']


def test_volatile_entry_snapshot_converts_to_detached_mutable_transport_config():
    raw=dict(servers=dict(local=dict(transport='stdio',command='controlled',args=['one'],env=dict(TOKEN='${credential:TOKEN}'))))
    resolved=MANAGER_CONFIG(raw);snapshot=resolved['servers'].get()
    validate_entries(snapshot)
    raw['servers']['local']['args'].append('mutated raw')
    assert snapshot['local']['args']==['one']
    with pytest.raises(TypeError):snapshot['local']['env']['TOKEN']='refused'
    client=to_client_config('local',snapshot['local'])
    client['args'].append('client-only');client['env']['TOKEN']='client-only'
    assert snapshot['local']['args']==['one']
    assert snapshot['local']['env']['TOKEN']=='${credential:TOKEN}'
    assert MANAGER_CONFIG({})['servers'].get()=={}
