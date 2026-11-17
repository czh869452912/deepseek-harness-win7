import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.client import product_analytics_current as module
from dsh.cordis import Context
from dsh.cordis.volatile import updateVolatile,createVolatile
from dsh.core.abort import AbortController
from dsh.session.otel_service_current import CurrentOTel
from dsh.typert.remote import remote_methods
from scripts.rc022_product_analytics_probe import observe,cases
from test_rc022_product_telemetry import collectors


@pytest.mark.asyncio
async def test_mounted_host_policy_caching_identity_and_disposal_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'product-analytics-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==41
    assert rows[0]['identityCalls']==2 and len(rows[0]['samples'])==1
    assert rows[0]['records'][0]['attributes']['device_id']=='device-1'
    assert rows[0]['records'][1]['attributes']['device_id']=='device-2'
    assert not rows[1]['records'] and not rows[1]['samples'] and not rows[1]['identityCalls']
    assert rows[3]['policy']==[True,True,False,'done',False]
    assert rows[4]['records'][0]['attributes']['trigger_type']=='manual'
    assert rows[4]['records'][1]['attributes']['trigger_type']=='auto'
    assert all(not row['after'] for row in rows)


def services(ctx,identity=None):
    async def get():return identity
    records=[]
    ctx.set_service('deepseekAccount',SimpleNamespace(getDeviceIdentity=get))
    ctx.set_service('productTelemetry',SimpleNamespace(emit=records.append))
    return records


@pytest.mark.asyncio
async def test_disposal_aborts_and_awaits_shared_sampling_and_closes_policy(monkeypatch):
    ctx=Context();records=services(ctx);entered=asyncio.Event();aborted=asyncio.Event();release=asyncio.Event();calls=[]
    async def collect(options):
        calls.append(options);entered.set()
        await options['signal'].wait_aborted();aborted.set();await release.wait()
        return dict(os_name='windows',missing_fields={})
    monkeypatch.setattr(module,'collectEnvironment',collect)
    fiber=await ctx.plugin(module.CurrentProductAnalytics,{})
    service=ctx.get('productAnalytics');cancellation=AbortController();iterator=service.watchPolicy(cancellation.signal)
    assert await iterator.__anext__() is True
    reports=[service.report(dict(eventName='auth_page_view',timestamp=n,attributes={})) for n in [1,2]]
    await entered.wait();assert len(calls)==1
    disposal=asyncio.ensure_future(fiber.dispose());await aborted.wait()
    assert not disposal.done() and not records
    with pytest.raises(StopAsyncIteration):await iterator.__anext__()
    assert not service.listeners and not cancellation.signal._listeners
    release.set();await asyncio.gather(*reports,disposal)
    assert not records and service.enabled() is False
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_live_policy_change_during_identity_lookup_drops_pending_intake(monkeypatch):
    ctx=Context();records=services(ctx);identity=asyncio.get_running_loop().create_future()
    ctx.get('deepseekAccount').getDeviceIdentity=lambda:identity
    async def collect(options):return dict(os_name='windows',missing_fields={})
    monkeypatch.setattr(module,'collectEnvironment',collect)
    fiber=await ctx.plugin(module.CurrentProductAnalytics,{})
    service=ctx.get('productAnalytics');report=service.report(dict(eventName='auth_page_view',timestamp=1,attributes={}))
    updateVolatile(fiber.effectiveConfig['enabled'],createVolatile(False));fiber.ctx.emit('loader/volatile-update',[['enabled']])
    identity.set_result(dict(deviceId='device'));await report
    assert not records
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_environment_rejection_is_cached_and_warns_without_emitting(monkeypatch):
    ctx=Context();records=services(ctx);samples=[];warnings=[]
    ctx.logger.warn=lambda message,*_:warnings.append(message)
    async def collect(options):samples.append(1);raise RuntimeError('private environment failure')
    monkeypatch.setattr(module,'collectEnvironment',collect)
    fiber=await ctx.plugin(module.CurrentProductAnalytics,{})
    for _ in range(2):await ctx.get('productAnalytics').report(dict(eventName='auth_page_view',attributes={}))
    assert samples==[1] and not records and warnings==['Product analytics submission failed']*2
    # Source disposal awaits the same rejected sample; preserve that failure.
    await fiber.dispose()
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_registry_host_remote_and_actual_collector_channel(collectors,monkeypatch):
    async def collect(options):return dict(os_name='windows',app_arch='x64',missing_fields={'os_build':'timeout'})
    monkeypatch.setattr(module,'collectEnvironment',collect)
    collector=collectors();ctx=Context();await ctx.plugin(CurrentOTel)
    async def identity():return dict(deviceId='device',userId='user',ignored='private')
    ctx.set_service('deepseekAccount',SimpleNamespace(getDeviceIdentity=identity))
    telemetry=await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-host-product-telemetry-otel'),dict(
        endpoint=collector.url,serviceName='fixture-desktop',serviceVersion='1',compression='none',scheduledDelayMillis=100000))
    analytics=await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-client-product-analytics'),dict(appVersion='fixture-version'))
    service=ctx.get('productAnalytics')
    assert {item['method'] for item in remote_methods(service.typertRemote['service'])}=={'enabled','watchPolicy','report'}
    await service.report(dict(eventName='auth_page_view',timestamp=1800000000000,attributes=dict(button_name='sign_in')))
    assert not collector.hits
    await analytics.dispose();await telemetry.dispose()
    document=collector.hits[0]['document']['resourceLogs'][0]
    record=document['scopeLogs'][0]['logRecords'][0]
    attributes={item['key']:item['value']['stringValue'] for item in record['attributes']}
    assert record['body']=={'stringValue':'auth_page_view'}
    assert attributes==dict(button_name='sign_in',os_name='windows',app_arch='x64',missing_fields='os_build=timeout',device_id='device',user_id='user',app_version='fixture-version')
    assert collector.hits[0]['channel']=='dsh_otel_report'
    await ctx.fiber.dispose()
