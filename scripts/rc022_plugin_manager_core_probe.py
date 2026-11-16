"""Real Include/Loader/HMR profile management and operation facts."""
import asyncio
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    return ['live','startup','overlay','pending','reload-error','lock-error','unloaded','foreign','diagnostic-failure']


async def observe(workspace=None):
    from dsh.boot.app_boot import boot
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.boot.profile_context import read_profile_patches
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    output=[]
    for mode in corpus():
        home=(workspace or WORKSPACE)/'native'/mode;directory=home/'profile';bundle=directory/'node_modules/core';bundle.mkdir(parents=True)
        def write(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        write(home/'package.json',dict(name='installation'))
        write(directory/'package.json',dict(name='profile',dsh=dict(profile=dict(bundles=['core']))))
        write(bundle/'package.json',dict(name='core',version='1.0.0',dsh=dict(bundle=dict(patch='cordis.patch.yml'))))
        write(bundle/'cordis.patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=dict(lockWaitMs=0)),dict(id='managed',name='cordis:active')])])
        write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[])
        profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core'],overlays=[dict(id='managed',disabled=True)] if mode=='overlay' else [])
        def setup(ctx):
            ctx.provide('profileContext',profile)
            ctx.provide('appReady',NS(onReady=lambda listener:(listener(),lambda:None)[1]))
            ctx.loader.builtins.update(manager=CurrentPluginManager,active=lambda owner,config:owner.provide('managedProbe',True))
        ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
        operations=[];changed=[];identities=[]
        ctx.on('plugin-manager/operation',lambda event:operations.append(event))
        ctx.on('plugin-manager/changed',lambda event:changed.append(event))
        async def drain():
            for _ in range(15):await asyncio.sleep(0)
        try:
            manager=ctx.pluginManager
            if mode=='diagnostic-failure':
                def failed(event):raise RuntimeError('diagnostic unavailable')
                ctx.on('plugin-manager/operation',failed)
            if mode!='startup':
                await ctx.plugin(TimerService)
                await ctx.plugin(ConfigWatcherService,dict(root=[],ignored=[],debounce=0))
                await ctx.hmr.runExclusive(lambda:None)
            if mode=='foreign':await ctx.loader.create(dict(id='foreign',name='cordis:active'))
            initial=await manager.listPlugins()
            steps=[]
            if mode=='pending':
                async def pending(required):return dict(warnings=['existing inactive'],pending=[dict(reason='host-module')])
                ctx.hmr.reconcileProfile=pending
            if mode=='reload-error':
                async def failed(required):raise RuntimeError('reload failed')
                ctx.hmr.reconcileProfile=failed
            if mode=='unloaded':await ctx.loader.resolve('include:manager').fiber.dispose()
            lock=directory/'package.json.lock'
            if mode=='lock-error':lock.write_text('owned test lock',encoding='utf-8')
            try:
                actions=[('include:managed',False),('include:managed',False),('include:managed',True),('include:manager',False),('missing',True)]
                if mode=='foreign':actions.append(('foreign',False))
                for identity,enabled in actions:
                    try:result=await manager.setPluginEnabled(identity,enabled)
                    except Exception:result=dict(threw=True)
                    await drain()
                    rows=await manager.listPlugins() if mode!='unloaded' else []
                    steps.append(dict(result=result,managed=next((row for row in rows if row['entryId']=='include:managed'),None)))
            finally:
                if lock.exists():lock.unlink()
            await drain()
            facts=[]
            for event in operations:
                if event['id'] not in identities:identities.append(event['id'])
                facts.append(dict({key:value for key,value in event.items() if key not in ('id','time')},operation=identities.index(event['id']),validTime=bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z',event['time']))))
            output.append(dict(name=mode,initial=initial,steps=steps,changed=changed,facts=facts,lockReleased=not lock.exists()))
        finally:await ctx.fiber.dispose()
    return output


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_plugin_manager_core.mts','Actual PluginManager, Include, Loader and HMR over real profiles. Plugin target ownership/self protection, live/startup/overlay changes, no-op and redundant override removal, unknown/foreign refusals, pending and failed reload, lock and unload rejection, changed notifications and paired operation facts. Package install APIs are outside this core batch.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_manager_current.py',ROOT/'dsh/boot/plugin_switch.py'],prepare=prepare)
