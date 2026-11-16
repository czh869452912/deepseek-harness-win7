import asyncio
import copy
import json

import pytest

from dsh.client.analytics_environment_current import collectEnvironment,EXTRA_FIELDS
from scripts.rc022_analytics_environment_probe import observe,cases,fixtures


@pytest.mark.asyncio
async def test_static_metadata_parsing_fixed_queries_and_failure_isolation_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'analytics-environment-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==136
    base=rows[0]
    assert base['value']['os_version_full']=='10.0.26100.1'
    assert base['value']['os_arch']=='x64' and base['value']['cpu_physical_core_count']==4
    assert len(base['calls'])==2
    assert all(call['args'][:3]==['-NoProfile','-NonInteractive','-EncodedCommand'] for call in base['calls'])
    allowed={'os_name','app_arch','os_version','os_version_full','os_build','os_arch','cpu_model',
        'cpu_logical_count','cpu_physical_core_count','memory_total_bytes','missing_fields'}
    for entry,row in zip(cases(),rows):
        assert set(row['value'])<=allowed
        assert set(row['value']['missing_fields'].values())<={'unavailable','invalid-value','unsupported','query-failed','timeout','output-limit'}
        if entry.get('sources',{}).get('platform') in ('linux','freebsd','aix'):
            assert not row['calls'] and all(row['value']['missing_fields'][field]=='unsupported' for field in EXTRA_FIELDS)


@pytest.mark.asyncio
async def test_independent_version_and_cpu_queries_start_concurrently_and_keep_failure_local():
    selected,version,cpu=fixtures({});entered=set();both=asyncio.Event();release=asyncio.Event()
    sources=dict(selected)
    for field in ['platform','release','totalmem','cpus']:sources[field]=lambda field=field:copy.deepcopy(selected[field])
    async def query(command,args,options):
        import base64
        is_cpu='Get-CimInstance' in base64.b64decode(args[-1]).decode('utf-16-le')
        entered.add(is_cpu)
        if len(entered)==2:both.set()
        await release.wait()
        return cpu if is_cpu else dict(kind='missing',reason='timeout',stderr='synthetic private command output')
    operation=asyncio.create_task(collectEnvironment(dict(timeoutMillis=10,maxOutputBytes=100),sources,query))
    try:
        await asyncio.wait_for(both.wait(),1);assert not operation.done()
        release.set();value=await operation
        assert value['os_arch']=='x64' and value['cpu_physical_core_count']==4
        assert value['missing_fields']=={'os_version_full':'timeout','os_build':'timeout'}
        assert 'synthetic private command output' not in json.dumps(value)
    finally:
        release.set();await operation
