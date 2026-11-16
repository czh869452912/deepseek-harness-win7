"""Actual product telemetry policy/configuration over an independent event reporter port."""
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
    rows=[dict(config={}),dict(config=dict(compression='gzip')),dict(config=dict(shutdownTimeoutMillis=1),action='deadline')]
    values=[None,False,0,-1,1,1.0,1.5,2147483647,2147483648,'1',{},[]]
    for field in ['maxExportBatchSize','maxQueueSize','scheduledDelayMillis','timeoutMillis','exportTimeoutMillis','shutdownTimeoutMillis']:
        rows += [dict(config={field:value}) for value in values]
    for field in ['serviceName','serviceVersion']:
        rows += [dict(config={field:value}) for value in [None,False,0,'','fixture',{},[]]]
        rows.append(dict(config={},omit=field))
    rows += [dict(config=dict(endpoint=value)) for value in [None,'','relative','file:///logs','ftp://fixture.test','mailto:a@b',
        'http://fixture.test/logs','https://fixture.test/logs','http://fixture.test:70000','http:///fixture.test/logs']]
    rows += [dict(config=dict(channel=value)) for value in [None,'','fixture','\t','line\nvalue','\x00','\x7f','\xff','\u0100','\ud800']]
    rows += [dict(config=dict(compression=value)) for value in [None,'none','gzip','bad',False,0,{},[]]]
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.json_text import stringify_json
    from dsh.host.product_telemetry_current import CurrentProductTelemetry
    rows=[]
    for entry in cases():
        ctx=Context();options=[];records=[];warnings=[];shutdown=[];stage='schema';error=None;fiber=None
        ctx.logger.warn=lambda message,*_:warnings.append(str(message)) if str(message).startswith('Product telemetry') else None
        async def stop(signal):
            if entry.get('action')=='deadline':await signal.wait_aborted()
            shutdown.append(dict(aborted=signal.aborted,reason=str(signal.reason) if signal.aborted else None))
        def create(selected):
            options.append({key:value for key,value in selected.items() if key!='onFailure'})
            return SimpleNamespace(emit=lambda record:records.append(copy.deepcopy(record)),shutdown=stop)
        ctx.set_service('otel',SimpleNamespace(createEventReporter=create))
        config=dict(serviceName='fixture',serviceVersion='1',**{key:value for key,value in entry['config'].items() if key not in ('serviceName','serviceVersion')})
        for key in ('serviceName','serviceVersion'):
            if key in entry['config']:config[key]=entry['config'][key]
        if entry.get('omit'):config.pop(entry['omit'])
        try:
            parsed=CurrentProductTelemetry.Config(config);stage='construct'
            fiber=ctx.plugin(CurrentProductTelemetry,parsed);await fiber
            ctx.get('productTelemetry').emit(dict(eventName='fixture',body='synthetic',timestamp=1700000000000,attributes={'platform':'win32'}))
            await fiber.dispose();stage='done'
        except Exception as failure:
            if stage=='construct':error=str(failure)
        finally:await ctx.fiber.dispose()
        row=dict(stage=stage,error=error,options=options,records=records,warnings=warnings,shutdown=shutdown,
            after=ctx.get('productTelemetry',False) is not None)
        rows.append(json.loads(stringify_json(row)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_product_telemetry.mts','Mounted product telemetry policy: schema defaults/bounds, endpoint/channel checks, explicit resource/routing options, pass-through event port and cancelling disposal deadline.',
        [Path(__file__).resolve(),ROOT/'dsh/host/product_telemetry_current.py',ROOT/'packages/host/product-telemetry-otel/package.json'],prepare=prepare)
