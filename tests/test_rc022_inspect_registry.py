import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.extensions.inspect_registry_current import CurrentCordisInspectRegistryService
from scripts.rc022_inspect_registry_probe import Clock, flush, manifest, observe


@pytest.mark.asyncio
async def test_current_inspect_registry_observations(tmp_path):
    rows=await observe()
    (tmp_path/'inspect-registry-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==26
    by_mode={row['mode']:row for row in rows}
    assert all(row['pending']==row['timers']==row['listeners']==0 for row in rows)
    assert by_mode['sync-success']['initial']==dict(requests=1,timers=1,pending=0)
    assert by_mode['offline']['initial']==dict(requests=0,timers=0,pending=0)
    assert by_mode['host-snapshot']['results']==[dict(value=dict(name='mutated'))]
    assert 'Client failure: provider-error: page failed' in by_mode['first-failure']['results'][0]['error']
    assert 'second failure' not in by_mode['first-failure']['results'][0]['error']
    assert by_mode['invalid-success']['acks']==[dict(accepted=False),dict(accepted=True)]
    assert by_mode['late-success']['acks']==[dict(accepted=False)]
    assert by_mode['notify-dispose']['logs']==[['[cordis-host-runner] notifying Client inspect completion failed:','notify failed']]


@pytest.mark.asyncio
@pytest.mark.parametrize('before_start',[True,False])
async def test_native_task_cancellation_waits_for_request_retirement(monkeypatch,before_start):
    ctx=Context();fiber=ctx.plugin(CurrentCordisInspectRegistryService,100);await fiber
    registry=ctx.get('cordisInspect');registry.syncClientManifest([manifest()])
    clock=Clock();monkeypatch.setattr(asyncio.get_running_loop(),'call_later',clock.later)
    controller=AbortController();requests=[];resolved=[]
    ctx.on('cordis/inspect-query',lambda row:requests.append(row))
    ctx.on('cordis/inspect-query-resolved',lambda row:resolved.append(row))
    try:
        task=asyncio.create_task(registry.query('client','Service','listService',{},NS(id='owner'),controller.signal))
        assert len(requests)==1 and len(clock.pending)==1
        if not before_start:await flush()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not registry._pending and not clock.pending and not controller.signal._listeners
        assert resolved==[dict(requestId='inspect-1')]
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_host_abort_identity_and_output_validation_run_after_await():
    ctx=Context();fiber=ctx.plugin(CurrentCordisInspectRegistryService,1);await fiber
    registry=ctx.get('cordisInspect');controller=AbortController();reason=ValueError('own reason')
    registry.register(dict(manifest=manifest(),query=lambda *_:dict(name='value')))
    try:
        task=asyncio.create_task(registry.query('host','Service','listService',{},NS(id='owner'),controller.signal))
        controller.abort(reason)
        with pytest.raises(ValueError) as caught:await task
        assert caught.value is reason
    finally:await ctx.fiber.dispose()
