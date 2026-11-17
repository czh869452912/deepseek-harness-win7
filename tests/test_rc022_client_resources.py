import asyncio
import json

import pytest

from dsh.host.client_modules.resources_current import LazyBody
from scripts.rc022_client_resources_probe import prepare,observe


@pytest.mark.asyncio
async def test_current_lazy_resources_observations(tmp_path):
    prepare(tmp_path);rows=await observe(tmp_path/'files')
    (tmp_path/'client-resources-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    stages={row['stage']:row for row in rows}
    assert len(rows)==13
    assert not stages['script-first']['reads'] and not stages['map-head']['reads']
    assert stages['map-first']['body']==stages['map-cached']['body']
    assert stages['single-map']['body']==stages['single-map-after-compose']['body']
    assert stages['script-first']['body']==stages['prior-batch']['body']
    assert 'src/first.ts' in stages['map-first']['body']
    assert 'src/second.ts' in stages['single-map']['body']
    assert stages['unknown']['status']==404 and stages['post']['status']==405
    assert '/plugins/fixture-lazy/client.js' in stages['malformed-map']['body']


@pytest.mark.asyncio
async def test_lazy_body_shared_failure_retry_and_carrier_cancellation():
    entered=asyncio.Event();release=asyncio.Event();calls=[];payload=b'held body'
    async def produce():
        calls.append(True);entered.set();await release.wait()
        if len(calls)==1:raise ValueError('download failed')
        return payload
    lazy=LazyBody(produce)
    first=asyncio.create_task(lazy());second=asyncio.create_task(lazy())
    await entered.wait();first.cancel()
    with pytest.raises(asyncio.CancelledError):await first
    assert not lazy.task.done() and len(calls)==1
    release.set()
    with pytest.raises(ValueError,match='download failed'):await second
    assert lazy.task is None
    left,right=await asyncio.gather(lazy(),lazy())
    assert left is payload and right is payload and len(calls)==2
