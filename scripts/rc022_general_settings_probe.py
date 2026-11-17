"""Live welcome acknowledgement configuration without a settings section."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context,Loader
    from dsh.client.appearance_current import CurrentGeneralSettingsHost
    from dsh.cordis.utils import _UNDEFINED
    ctx=Context();loader=Loader(ctx);ctx.set_service('loader',loader);rows=[];calls=[]
    try:
        def configure(policy,owner):calls.append(dict(policy=policy,entry=owner.entry.id));return lambda:calls.append('released')
        ctx.provide('settings',SimpleNamespace(configure=configure))
        loader.register_plugin_class('general',CurrentGeneralSettingsHost)
        key=await loader.create(dict(id='general',name='general',config={}));entry=loader.resolve(key);fiber=entry.fiber;await fiber
        for value in [{},dict(welcomeNoticeVersion='v1'),dict(welcomeNoticeVersion='0.2'),{}]:
            await entry.update(dict(config=value));await entry.fiber
            ref=fiber.effectiveConfig['welcomeNoticeVersion'].get()
            rows.append(dict(step='value',value={} if ref is _UNDEFINED else dict(welcomeNoticeVersion=ref),sameFiber=entry.fiber is fiber))
        for value in [None,7,False,[]]:
            try:fiber.resolveConfig(dict(welcomeNoticeVersion=value));accepted=True
            except Exception:accepted=False
            rows.append(dict(step='invalid',input=value,accepted=accepted))
        rows.append(dict(step='settings',calls=list(calls)));await fiber.dispose();rows.append(dict(step='disposed',calls=list(calls)))
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_general_settings.mts','Welcome acknowledgement optional volatile string, live replacement/clearing, invalid values and reversible Settings auto:false policy.',[Path(__file__).resolve(),ROOT/'dsh/client/appearance_current.py'])
