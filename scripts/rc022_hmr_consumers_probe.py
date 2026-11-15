"""Partial module replacement across live configuration and ownership consumers."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
MODES=['volatile','provider','children','removed-traversal']

def prepare(output):
 global OUTPUT
 OUTPUT=output
 p=output/'input.json';p.write_text(json.dumps(MODES),encoding='utf-8');return [p]

async def observe(directory):
 from dsh.cordis import Context,Loader,Schema as z
 from dsh.cordis.timer import TimerService
 from dsh.cordis.hmr import ConfigWatcherService
 from dsh.cordis.hmr_modules import module_url
 directory.mkdir(parents=True);rows=[]
 for mode in MODES:
  owner=directory/mode;owner.mkdir();source=owner/'plugin.py';provider=owner/'provider.py';helper=owner/'_rc022_consumer_helper.py'
  helper.write_text('value=1\n',encoding='utf-8')
  def write(version):
   text='from dsh.cordis import Schema as z\n'
   if mode=='volatile':text+='Config=z.object({"value":z.string().volatile()})\n'
   if mode=='provider':text+='inject=["revision"]\n'
   if mode=='removed-traversal':text+='from '+helper.stem+' import value\n'
   text+='def apply(ctx,config):\n    records=ctx.get("records")\n'
   if mode=='volatile':text+='    records.append(config)\n'
   elif mode=='provider':text+='    records.append([config["value"],ctx.get("revision"),'+str(version)+'])\n'
   else:text+='    records.append("'+str(version)+':"+config["value"])\n'
   source.write_text(text,encoding='utf-8')
  write(1);ctx=Context();ctx.baseUrl=owner.as_uri()+'/';records=[];ctx.provide('records',records)
  await ctx.plugin(Loader);await ctx.plugin(TimerService);await ctx.plugin(ConfigWatcherService,dict(root=[]));loader,hmr=ctx.loader,ctx.get('hmr')
  sys.path.insert(0,str(owner))
  try:
   if mode=='provider':
    provider.write_text('def apply(ctx,config):\n    ctx.provide("revision",config["revision"])\n',encoding='utf-8')
    provider_entry=loader.resolve(await loader.create(dict(name=str(provider),config=dict(revision=1))))
   entry=loader.resolve(await loader.create(dict(name=str(source),config=dict(value='initial'))));await loader.await_();namespace=entry.moduleNamespace
   if mode=='volatile':
    await entry.update(dict(config=dict(value='current')));await loader.await_();old=records[0]['value'];before=len(records)
   if mode=='children':
    plugin=loader.unwrap_exports(namespace)
    await entry.fiber.ctx.plugin(plugin,dict(value='child'));await ctx.plugin(plugin,dict(value='independent'))
   write(2)
   if mode=='removed-traversal':
    reached,release=asyncio.Event(),asyncio.Event();original=hmr.getLinked
    async def linked(url):
     if url==source.as_uri():reached.set();await release.wait()
     return await original(url)
    hmr.getLinked=linked;hmr._stashed[helper.as_uri()]=None;operation=hmr.runExclusive(lambda:hmr.partialReload())
    await asyncio.wait_for(reached.wait(),3);old_fiber=entry.fiber;await ctx.registry.delete_async(loader.unwrap_exports(namespace));release.set();await operation
    rows.append(dict(mode=mode,records=list(records),replacement_active=ctx.registry.get(loader.unwrap_exports(entry.moduleNamespace)) is not None,old_retired=old_fiber.uid is None,namespace_changed=entry.moduleNamespace is not namespace))
   else:
    hmr._stashed[source.as_uri()]=None;await hmr.runExclusive(lambda:hmr.partialReload())
    if mode=='volatile':
     new=records[-1]['value'];changed=new is not old;at_reload=new.get();await entry.update(dict(config=dict(value='after-reload')));await loader.await_()
     rows.append(dict(mode=mode,before=before,activations=len(records),distinct=changed,at_reload=at_reload,new=new.get(),old=old.get()))
    elif mode=='provider':
     await asyncio.gather(provider_entry.update(dict(config=dict(revision=2))),entry.update(dict(config=dict(value='updated'))));await loader.await_()
     rows.append(dict(mode=mode,last=records[-1],namespace_changed=entry.moduleNamespace is not namespace))
    else:rows.append(dict(mode=mode,records=list(records),instances=len(list(entry.fiber.runtime.fibers))))
  finally:
   await ctx.fiber.dispose();sys.path.remove(str(owner))
   for name,module in list(sys.modules.items()):
    url=module_url(module)
    if url and url.startswith(owner.as_uri()+'/'):sys.modules.pop(name,None)
 return rows

async def native():return await asyncio.wait_for(observe(OUTPUT/'files/native'),25)
if __name__=='__main__':
 probe.native=native
 probe.main('rc022_hmr_consumers.mts','Actual module replacement across volatile references, provider/consumer updates, parent/child instance ownership and runtime removal during evaluated dependency traversal.',[Path(__file__).resolve(),ROOT/'dsh/cordis/hmr_partial.py',ROOT/'dsh/cordis/hmr_changes.py',ROOT/'dsh/cordis/hmr_modules.py',ROOT/'dsh/cordis/loader.py',ROOT/'dsh/cordis/fiber.py',*[ROOT/'.goose/out/rc022-prep-20261114-01/source'/part for part in ('packages/boot/hmr/lib/index.js','vendor/cordis/lib/index.js','vendor/loader/lib/index.js','vendor/timer/lib/index.js','vendor/schemastery/lib/index.mjs','packages/boot/hmr/src/index.ts')]],prepare,node_args=('--expose-internals',),plain_node=True)
