import asyncio
import threading
import pytest
from scripts.rc022_detail_http_probe import observe,Servers
from dsh.util.plugin_detail_http import fetch_body


@pytest.mark.asyncio
async def test_real_bounded_http_and_cdn_fallback_contracts():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==23
    assert rows['ok']['result']==dict(value=dict(ok=True,bytes='ok'))
    assert rows['redirect']['result']==rows['ok']['result']
    for name in ('cross','loop','bare'):assert rows[name]['result']==dict(value=dict(ok=False,status=302))
    for name in ('large','declared','gzip-large'):assert rows[name]['result']==dict(error='too-large')
    for name in ('headers','body','broken'):assert rows[name]['result']==dict(error='network')
    for name in ('cancel','dispose'):assert rows[name]['result']==dict(error='closed')
    assert rows['gzip']['result']==dict(value=dict(ok=True,bytes='decoded'))
    assert rows['npm-missing']['result']==dict(value=None) and len(rows['npm-missing']['requests'])==1
    assert len(rows['npm-fallback']['requests'])==2
    assert rows['npm-cancelled']['result']==dict(error='closed')


@pytest.mark.asyncio
async def test_task_cancellation_joins_owned_http_worker_and_detaches_signals():
    from dsh.core.abort import AbortController
    signal,lifetime=AbortController(),AbortController()
    servers=Servers()
    try:
        task=asyncio.create_task(fetch_body(servers.url+'/headers',100,signal.signal,dict(timeoutMs=2000,lifetime=lifetime.signal)))
        for _ in range(100):
            if servers.requests:break
            await asyncio.sleep(.01)
        assert servers.requests
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not any(thread.name=='dsh-http-cancellation' for thread in threading.enumerate())
        signal.abort();lifetime.abort()
    finally:servers.close()
