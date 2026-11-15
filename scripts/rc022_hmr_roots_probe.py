"""Compare actual change-only watcher roots and ignore configuration."""
import asyncio
import json
from pathlib import Path
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
CASES=[dict(name='defaults'),dict(name='empty',ignored=[]),dict(name='scoped',ignored=['**/skip','*.tmp']),dict(name='file',root=['top.txt'],ignored=[]),dict(name='depth',depth=0,ignored=[]),dict(name='literal-root',root=['*.txt'],ignored=[]),dict(name='relative-base',base='project',ignored=[]),dict(name='linked-root',root=['alias'],ignored=[]),dict(name='unfollowed-root',root=['alias'],ignored=[],followSymlinks=False)]
PATTERNS=['**/.*','*.tmp','**/*.py','cache','**/node_modules','foo/**','**','*','a?','[ab].txt','[!a].txt','{foo,bar}/**','foo/*/bar','!*.tmp','./*.txt','*.JS','foo/**/bar','**/.{a,b}','foo/*','foo/**/']
PATHS=['','a','.a','a.txt','.a.txt','..','foo','foo/','foo/bar','foo/.a','foo/.a/bar','foo/x/bar','foo/x/y/bar','foo\\bar','foo\\x\\bar','a.tmp','b.txt','foo/a.tmp','foo\\a.tmp','foo/a.py','foo\\a.py','node_modules','a/node_modules','a\\node_modules','file.JS','file.js','foo/a','foo/b','bar/b']
FILES=['top.txt','top.tmp','.hidden','node_modules/pkg.txt','cache/a.txt','data/a.txt','dist/a.txt','build/a.txt','venv/a.txt','sub/a.txt','sub/skip/a.txt','skip/a.txt','sub/other.tmp','sub/.secret/a.txt']

def prepare(output):
 global OUTPUT
 OUTPUT=output
 p=output/'input.json';p.write_text(json.dumps(dict(cases=CASES,files=FILES,patterns=PATTERNS,paths=PATHS)),encoding='utf-8');return [p]

async def observe(directory):
 from dsh.cordis.context import Context
 from dsh.cordis.loader import Loader
 from dsh.cordis.timer import TimerService
 from dsh.cordis.hmr import ConfigWatcherService
 from dsh.cordis.hmr_paths import file_path
 directory.mkdir(parents=True);result=[]
 for config in CASES:
  owner=directory/config['name'];base=owner/('project' if 'base' in config else '')
  for name in FILES:
   p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('before',encoding='utf-8')
  if 'linked-root' == config['name'] or 'unfollowed-root' == config['name']:
   if os.name=='nt':
    import _winapi
    _winapi.CreateJunction(str(base/'sub'),str(base/'alias'))
   else:(base/'alias').symlink_to(base/'sub',target_is_directory=True)
  ctx=Context();ctx.baseUrl=owner.as_uri()+'/'
  await ctx.plugin(Loader);await ctx.plugin(TimerService)
  try:
   await ctx.plugin(ConfigWatcherService,dict({'root':['.'],'debounce':0},**{k:v for k,v in config.items() if k!='name'}))
   hmr=ctx.get('hmr');events=[];ctx.on('hmr/change',lambda url:events.append(Path(file_path(url)).relative_to(base).as_posix()))
   ready=hmr._initial_scanned
   for name in FILES:(base/name).write_text('after-'+name,encoding='utf-8')
   await asyncio.sleep(.35);await hmr.runExclusive(lambda:None)
   result.append(dict(name=config['name'],ready=ready,events=sorted(set(events))))
   if config['name']=='empty':
    events.clear();added=base/'added.txt';added.write_text('new',encoding='utf-8');await asyncio.sleep(.15)
    baseline=list(events);added.write_text('updated',encoding='utf-8');await asyncio.sleep(.15)
    changes=list(events);events.clear();added.unlink();await asyncio.sleep(.15);deleted=list(events)
    added.write_text('restored',encoding='utf-8');await asyncio.sleep(.15);restored=list(events)
    added.write_text('restored-edited',encoding='utf-8');await asyncio.sleep(.15);await hmr.runExclusive(lambda:None)
    result.append(dict(name='membership',added=baseline,changed=changes,deleted=deleted,restored=restored,rechanged=list(events)))
  finally:await ctx.fiber.dispose()
 from dsh.cordis.hmr_glob import matches
 result.append(dict(name="ignore-patterns",values=[matches(path,[pattern]) for pattern in PATTERNS for path in PATHS]))
 return result

async def native():return await asyncio.wait_for(observe(OUTPUT/'files/native'),15)
if __name__=='__main__':
 probe.native=native
 probe.main('rc022_hmr_roots.mts','Actual root watchers: defaults versus explicit empty ignores, path-relative globs, file roots, depth, literal non-glob roots, relative base and startup inventory.',[Path(__file__).resolve(),ROOT/'dsh/cordis/hmr.py',ROOT/'dsh/cordis/hmr_root_watch.py',ROOT/'dsh/cordis/hmr_glob.py',ROOT/'dsh/cordis/hmr_modules.py',*[ROOT/'.goose/out/rc022-prep-20261114-01/source'/part for part in ('packages/boot/hmr/src/index.ts','packages/boot/hmr/lib/index.js','vendor/cordis/lib/index.js','vendor/loader/lib/index.js','vendor/timer/lib/index.js')]],prepare,node_args=('--expose-internals',),plain_node=True)
