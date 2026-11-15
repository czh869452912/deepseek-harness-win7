"""Pair actual writes, atomic replacements and pending watcher teardown."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
CASES=[dict(name='plain'),dict(name='stable',awaitWriteFinish=dict(stabilityThreshold=300,pollInterval=20)),dict(name='stable-dispose',awaitWriteFinish=dict(stabilityThreshold=300,pollInterval=20)),dict(name='atomic-default',gap=60),dict(name='atomic-disabled',gap=60,atomic=False),dict(name='atomic-window',gap=160,atomic=400),dict(name='atomic-expired',gap=180),dict(name='editor-default',editor=True),dict(name='editor-disabled',editor=True,atomic=False)]
def prepare(output):
 global OUTPUT
 OUTPUT=output
 p=output/'input.json';p.write_text(json.dumps(CASES),encoding='utf-8');return [p]
async def observe(directory):
 from dsh.cordis.context import Context
 from dsh.cordis.loader import Loader
 from dsh.cordis.timer import TimerService
 from dsh.cordis.hmr import ConfigWatcherService
 from dsh.cordis.hmr_paths import file_path
 directory.mkdir(parents=True);rows=[]
 for case in CASES:
  base=directory/case['name'];base.mkdir();path=base/('file.txt~' if case.get('editor') else 'file.txt');path.write_text('initial',encoding='utf-8')
  ctx=Context();ctx.baseUrl=base.as_uri()+'/'
  await ctx.plugin(Loader);await ctx.plugin(TimerService)
  try:
   await ctx.plugin(ConfigWatcherService,dict(root=['.'],ignored=[],debounce=0,**{k:v for k,v in case.items() if k not in ('name','gap','editor')}));hmr=ctx.get('hmr');events=[]
   ctx.on('hmr/change',lambda url:events.append(Path(file_path(url)).read_text(encoding='utf-8')))
   if 'gap' in case:
    path.unlink();await asyncio.sleep(case['gap']/1000);path.write_text('replaced',encoding='utf-8');await asyncio.sleep(.5)
    rows.append(dict(name=case['name'],events=list(events)))
   elif case.get('editor'):
    path.write_text('edited',encoding='utf-8');await asyncio.sleep(.25);rows.append(dict(name=case['name'],events=list(events)))
   else:
    path.write_text('part-1',encoding='utf-8');await asyncio.sleep(.09);path.write_text('part-2-longer',encoding='utf-8');await asyncio.sleep(.09);early=list(events)
    if case['name']=='stable-dispose':
     await ctx.fiber.dispose();await asyncio.sleep(.4);rows.append(dict(name=case['name'],early=early,after=list(events)));continue
    await asyncio.sleep(.45);complete=list(events);events.clear()
    added=base/'added.txt';added.write_text('add-1',encoding='utf-8');await asyncio.sleep(.09);added.write_text('add-2-longer',encoding='utf-8');await asyncio.sleep(.45);new=list(events);events.clear()
    added.write_text('after-add',encoding='utf-8');await asyncio.sleep(.45);rows.append(dict(name=case['name'],early=early,complete=complete,added=new,changed=list(events)))
   await hmr.runExclusive(lambda:None)
  finally:await ctx.fiber.dispose()
 return rows
async def native():return await asyncio.wait_for(observe(OUTPUT/'files/native'),20)
if __name__=='__main__':
 probe.native=native
 probe.main('rc022_hmr_writes.mts','Actual write stability, add suppression, atomic unlink/add windows, editor temporary files and teardown while awaiting writes.',[Path(__file__).resolve(),ROOT/'dsh/cordis/hmr_root_watch.py',ROOT/'dsh/cordis/hmr.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/boot/hmr/node_modules/chokidar/index.js'],prepare,node_args=('--expose-internals',),plain_node=True)
