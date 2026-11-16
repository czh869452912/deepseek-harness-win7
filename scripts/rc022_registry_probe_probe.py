"""Actual registry-probe Remote with controlled headers, aborts and body ownership."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    return ['official','mirror','http-failure','offline','disabled','dispose','timeout','cleanup-wait','cleanup-reject','zero-ttl','caller-cancel']


async def observe():
    from dsh.cordis import Context
    from dsh.client.plugin_registry_probe import CurrentPluginRegistryProbe, REGISTRIES
    rows=[]
    for name in corpus():
        ctx=Context();requests=[];calls=[];releases=[];now=[1000]
        config=dict(registryProbeEnabled=name!='disabled',registryProbeTimeoutMs=10 if name=='timeout' else 5000,registryProbeCacheTtlMs=0 if name=='zero-ttl' else 50)
        owner=await ctx.plugin(CurrentPluginRegistryProbe,config);service=ctx.pluginRegistryProbe
        service._now=lambda:now[0]
        async def fetch(endpoint,signal,timeout,redirect):
            future=asyncio.get_running_loop().create_future()
            index=len(requests);requests.append(NS(future=future,signal=signal))
            calls.append(dict(endpoint=endpoint,redirect=redirect))
            def aborted(reason):
                if not future.done():future.set_exception(RuntimeError('aborted'))
            detach=signal.add_listener('abort',aborted)
            try:return await future
            finally:detach()
        service._fetch=fetch
        async def ticks():
            for _ in range(12):await asyncio.sleep(0)
        def answer(index,status=200):
            async def cancel():
                calls.append(dict(cancel=index))
                if name=='cleanup-wait':
                    gate=asyncio.get_running_loop().create_future();releases.append(gate);await gate
                if name=='cleanup-reject':raise RuntimeError('body already aborted')
            requests[index].future.set_result(NS(ok=200<=status<300,status=status,body=NS(cancel=cancel)))
        first=asyncio.create_task(service.fastest());shared=asyncio.create_task(service.fastest());await ticks()
        try:
            if name=='dispose':await owner.dispose()
            elif name in ('disabled','timeout'):pass
            elif name=='offline':
                requests[0].future.set_exception(RuntimeError('offline'));answer(1,500)
            elif name=='http-failure':answer(0,503);answer(1,204)
            elif name=='caller-cancel':
                first.cancel()
                try:await first
                except asyncio.CancelledError:pass
                answer(0)
            else:answer(1 if name in ('mirror','cleanup-reject') else 0)
            await ticks()
            blocked=not shared.done() if name=='cleanup-wait' else None
            for gate in releases:gate.set_result(None)
            value=await shared
            if name!='caller-cancel':assert await first==value
            cached=None;refreshed=None
            if name in ('official','mirror','offline'):
                cached=await service.fastest()
                if name!='offline':
                    now[0]=1050;fresh=asyncio.create_task(service.fastest());await ticks();answer(2,204);refreshed=await fresh
            if name=='zero-ttl':
                fresh=asyncio.create_task(service.fastest());await ticks();answer(3,204);refreshed=await fresh
            await owner.dispose()
            rejected=False
            try:await service.fastest()
            except Exception:rejected=True
            rows.append(dict(name=name,value=value,cached=cached,refreshed=refreshed,calls=calls,signals=[r.signal.aborted for r in requests],listeners=[len(r.signal._listeners) for r in requests],blocked=blocked,rejected=rejected,withdrawn=ctx.get('pluginRegistryProbe') is None))
        finally:
            for gate in releases:
                if not gate.done():gate.set_result(None)
            await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_registry_probe.mts','Actual registry-probe Remote race, shared pending, HTTP failure vs successful headers, positive/null/zero-TTL cache, expiry boundary, abort/timeout/disposal, response-body cleanup wait/failure and service withdrawal. Python waiter cancellation separately preserves shared ownership.',[Path(__file__).resolve(),ROOT/'dsh/client/plugin_registry_probe.py'],prepare=prepare)
