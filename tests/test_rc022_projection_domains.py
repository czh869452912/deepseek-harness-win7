import pytest
from scripts.rc022_projection_domains_probe import observe

@pytest.mark.asyncio
async def test_domain_plugins_wait_for_ready_registry_and_keep_full_views():
    rows=await observe()
    for row in rows:
        if row['case'].startswith('deferred'):
            assert row['waiting']==1 and row['ready']==2 and row['before']['values']=={}
            assert row['keys']==(['sessionStats'] if row['case']=='deferred-stats' else ['turnOutline'])
        elif row['case'] in ('fresh','late'):
            assert row['summary']['values']=={} and row['full']==row['cold']==row['remounted']
            assert row['full']['values']['sessionStats']['turns']==row['full']['values']['sessionStats']['steps']==1
            assert row['full']['values']['turnOutline']==[dict(turn=1,seq=0,prompt='',response='')]
            assert row['checkpointKeys']==row['retainedKeys']==['sessionStats','turnOutline']
            assert row['released']['values']=={}
