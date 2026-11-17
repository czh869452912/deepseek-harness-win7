import asyncio
import json
import os
import threading

import pytest

from dsh.client.analytics_os_current import collectEnvironment,default_sources
from dsh.core.abort import AbortController


@pytest.mark.asyncio
async def test_default_os_sampling_and_actual_bounded_queries(tmp_path):
    if os.name!='nt':pytest.skip('Windows static sampling qualification')
    selected=default_sources()
    assert selected['platform']()=='win32'
    assert selected['release']().count('.')==2
    assert selected['totalmem']()>0
    assert len(selected['cpus']())>0
    value=await asyncio.wait_for(collectEnvironment(dict(timeoutMillis=5000,maxOutputBytes=16384,
        signal=AbortController().signal)),8)
    (tmp_path/'analytics-os-observations.json').write_text(json.dumps(value),encoding='utf-8')
    assert value['os_name']=='windows' and value['app_arch'] in ('ia32','x64','arm64')
    assert value['cpu_logical_count']==len(selected['cpus']())
    assert value['memory_total_bytes']==selected['totalmem']()
    assert not any(t.name=='analytics-environment-query-reader' for t in threading.enumerate())
