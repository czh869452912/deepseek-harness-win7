import asyncio
import json
import sys
import pytest
from scripts.rc022_package_operations_probe import observe
from dsh.boot.plugin_package_operations import active_recorded_run,anchor_path_spec


@pytest.mark.asyncio
async def test_actual_service_mutations_admission_compatibility_and_restoration(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert rows['activate']['manifest']['dsh']['profile']['bundles']==['shipped','fresh']
    assert rows['inactive']['manifest']['dsh']['profile']['bundles']==['shipped']
    assert rows['platform']['result']['exitCode']==1
    assert rows['platform']['manifest']['dependencies']==dict(fresh='1.0.0')
    assert rows['expected']['result']['exitCode']==0
    assert rows['expected-wrong']['result']['unmet']=='unexpected-package'
    assert rows['expected-plain']['result']['unmet']=='not-bundle'
    assert rows['expected-extra']['result']['unmet']=='unexpected-package'
    assert rows['preflight']['runs'][0][0]=='view' and len(rows['preflight']['runs'])==1
    assert rows['preflight']['lock']=='original\r\n'
    for name in ('incompatible','component','changed-bad','dev-incompatible'):
        assert rows[name]['result']['exitCode']==1 and rows[name]['result']['incompatible']
        assert rows[name]['lock']=='original\r\n'
        assert rows[name]['runs'][-1]==['install','--frozen-lockfile']
    assert rows['without-lock']['lock'] is None
    assert rows['without-lock']['runs'][-1]==['install','--config.lockfile=false']
    assert 'could not be reinstalled' in rows['repair-failed']['result']['output']
    assert rows['untouched-bad']['result']['exitCode']==0
    assert 'stays installed' in rows['untouched-bad']['log']
    assert 'stays installed' not in rows['untouched-bad']['result']['output']
    assert rows['remove']['manifest']['dsh']['profile']['bundles']==['shipped']
    assert rows['invalid-record']['runs']==[] and not rows['invalid-record']['recordRemoved']
    assert rows['stale-record']['result']['exitCode']==0 and rows['stale-record']['recordRemoved']
    assert rows['numeric-order']['manifest']['dsh']['profile']['bundles']==['shipped','2','10']


@pytest.mark.asyncio
async def test_record_admission_keeps_active_or_unparseable_records(tmp_path):
    path=tmp_path/'.plugin-manager/run.json';path.parent.mkdir()
    for data in ('broken','null','{}','{"pid":true,"grouped":false}','{"pid":1,"grouped":0}','{"pid":9007199254740992,"grouped":false}'):
        path.write_text(data,encoding='utf-8')
        answer=await active_recorded_run(str(tmp_path),lambda tree:False,wait_ms=0)
        assert 'does not name a package run' in answer and path.read_text(encoding='utf-8')==data
    path.write_text('{"pid":42.0,"grouped":false}',encoding='utf-8')
    answer=await active_recorded_run(str(tmp_path),lambda tree:True,wait_ms=0)
    assert 'process 42' in answer and path.exists()
    calls=[]
    def disappearing(tree):calls.append(tree);return len(calls)==1
    assert await active_recorded_run(str(tmp_path),disappearing) is None
    assert not path.exists() and len(calls)>=2
    path.write_text('{"pid":9007199254740991,"grouped":false}',encoding='utf-8')
    assert await active_recorded_run(str(tmp_path),wait_ms=0) is None
    assert not path.exists()


def test_path_specs_anchor_only_dot_relative_forms(tmp_path):
    import os
    assert anchor_path_spec('file:../pkg',str(tmp_path))=='file:'+os.path.abspath(str(tmp_path/'../pkg'))
    assert anchor_path_spec('link:.',str(tmp_path))=='link:'+str(tmp_path)
    assert anchor_path_spec('@scope/pkg@1',str(tmp_path))=='@scope/pkg@1'
    assert anchor_path_spec('file:relative',str(tmp_path))=='file:relative'


@pytest.mark.asyncio
async def test_record_admission_waits_for_real_process_without_terminating_it(tmp_path):
    import subprocess
    path=tmp_path/'.plugin-manager/run.json';path.parent.mkdir()
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.3)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        path.write_text(json.dumps(dict(pid=process.pid,grouped=False)),encoding='utf-8')
        diagnostic=await active_recorded_run(str(tmp_path),wait_ms=0)
        assert 'still running in this profile' in diagnostic
        assert path.exists() and process.poll() is None
        assert await active_recorded_run(str(tmp_path),wait_ms=1000) is None
        assert not path.exists()
    finally:
        if process.poll() is None:process.terminate()
        process.wait(timeout=5)
