"""Mounted analytics policy/Remote intake with controlled OS and identity ports."""
import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[{},dict(config=dict(enabled=False)),dict(action='concurrent'),dict(action='policy'),dict(action='compaction')]
    for identity in [None,{},dict(deviceId=None,userId=None),dict(deviceId='device'),dict(userId='user'),dict(deviceId='device',userId='user',ignored='private')]:rows.append(dict(identity=identity))
    for failure in ['identity','sync-identity','emit']:rows.append(dict(failure=failure))
    for value in ['','fixture',None]:rows.append(dict(config=dict(appVersion=value)))
    for key in ['enabled','appVersion','environmentQueryTimeoutMillis','environmentQueryMaxOutputBytes']:
        for value in [False,0,-1,1.5,2147483648,'invalid']:
            rows.append(dict(config={key:value}))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.volatile import updateVolatile,createVolatile
    from dsh.core.abort import AbortController
    from dsh.client.analytics_environment_current import collectEnvironment
    from dsh.client import product_analytics_current as module
    rows=[];original=module.collectEnvironment
    try:
        for entry in cases():
            ctx=Context();records=[];warnings=[];identity_calls=[];samples=[];settings=[];policy=[]
            ctx.logger.warn=lambda message,*args:warnings.append(str(message)) if str(message).startswith('Product analytics') else None
            async def collect(options):
                samples.append(dict(timeoutMillis=options['timeoutMillis'],maxOutputBytes=options['maxOutputBytes']))
                return await collectEnvironment(options,dict(platform=lambda:'win32',app_arch='x64',SystemRoot=None,
                    release=lambda:'10.0.26300',totalmem=lambda:17179869184,cpus=lambda:[dict(model=' Fixture CPU '),dict(model='Fixture CPU')]),None)
            module.collectEnvironment=collect
            def identity():
                identity_calls.append(1)
                if entry.get('failure')=='sync-identity':raise RuntimeError('private identity failure')
                async def result():
                    if entry.get('failure')=='identity':raise RuntimeError('private identity failure')
                    return copy.deepcopy(entry.get('identity',dict(deviceId='device-'+str(len(identity_calls)),userId='user')))
                return result()
            def emit(record):
                if entry.get('failure')=='emit':raise RuntimeError('private emit failure')
                records.append(copy.deepcopy(record))
            def configure(options,fiber):
                settings.append(options)
                return lambda:settings.append('disposed')
            ctx.set_service('deepseekAccount',SimpleNamespace(getDeviceIdentity=identity))
            ctx.set_service('productTelemetry',SimpleNamespace(emit=emit))
            ctx.set_service('settings',SimpleNamespace(configure=configure))
            error=None;stage='schema';fiber=None
            try:
                config=module.CurrentProductAnalytics.Config(dict(entry.get('config',{})));stage='mount'
                fiber=await ctx.plugin(module.CurrentProductAnalytics,dict(entry.get('config',{})));service=ctx.get('productAnalytics')
                stage='done';policy.append(service.enabled())
                event=lambda timestamp:dict(eventName='auth_page_view',timestamp=timestamp,attributes=dict(os_name='caller',device_id='caller-device',app_version='caller-version'))
                if entry.get('action')=='policy':
                    cancellation=AbortController();iterator=service.watchPolicy(cancellation.signal)
                    policy.append(await iterator.__anext__())
                    pending=asyncio.create_task(iterator.__anext__());await asyncio.sleep(0)
                    updateVolatile(fiber.effectiveConfig['enabled'],createVolatile(False));fiber.ctx.emit('loader/volatile-update',[['enabled']])
                    policy.append(await pending);cancellation.abort()
                    try:await iterator.__anext__()
                    except StopAsyncIteration:policy.append('done')
                    await service.report(event(1))
                elif entry.get('action')=='compaction':
                    for turn in [None,'turn']:
                        ctx.emit('session/event',SimpleNamespace(id='session'),dict(type='compaction/start',data=dict(turn=turn)))
                    for _ in range(20):await asyncio.sleep(0)
                    for record in records:record['timestamp']='<now>'
                elif entry.get('action')=='concurrent':await asyncio.gather(service.report(event(1)),service.report(event(2)))
                else:
                    await service.report(event(1));await service.report(event(2))
                await fiber.dispose();policy.append(service.enabled())
            except Exception:
                if stage!='schema':raise
                error=stage
            finally:await ctx.fiber.dispose()
            rows.append(dict(stage=stage,error=error,records=records,warnings=warnings,identityCalls=len(identity_calls),samples=samples,settings=settings,policy=policy,after=ctx.get('productAnalytics',False) is not None))
    finally:module.collectEnvironment=original
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_product_analytics.mts','Actual mounted productAnalytics Host and Remote markers; controlled static OS/identity/telemetry ports, policy/schema defaults, metadata caching, fresh identity, event precedence, failures, compaction and reversible disposal.',
        [Path(__file__).resolve(),ROOT/'dsh/client/product_analytics_current.py',ROOT/'packages/client/product-analytics/package.json'],prepare=prepare)
