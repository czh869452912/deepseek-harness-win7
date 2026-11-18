"""Observe retired manifest policy and YAML-owned HMR defaults."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
VALUES=['__absent__','startup','live','sometimes',{'future':True}]

def prepare(output):
 global OUTPUT
 OUTPUT=output
 p=output/'input.json';p.write_text(json.dumps(VALUES),encoding='utf-8');return [p]

def observe(directory):
 from dsh.boot.profile import init_profile,load_profile_directory,load_profile,PROFILE_TEMPLATES,compose_entries
 from dsh.boot.app_boot import load_overlay_patches
 directory.mkdir(parents=True);result=[]
 anchor=directory/'install/package.json';anchor.parent.mkdir();anchor.write_text('{"name":"install"}',encoding='utf-8')
 for index,value in enumerate(VALUES):
  owner=directory/('legacy-'+str(index));init_profile(str(owner),[]);manifest=owner/'package.json';raw=json.loads(manifest.read_text(encoding='utf-8'))
  if value!='__absent__':raw['dsh']['profile']['patchReload']=value;manifest.write_text(json.dumps(raw),encoding='utf-8')
  before=manifest.read_bytes();loaded=load_profile_directory('test',str(owner),str(anchor))
  result.append(dict(kind='legacy',value=value,field=hasattr(loaded,'patchReload') or hasattr(loaded,'patch_reload'),unchanged=before==manifest.read_bytes(),manifest=json.loads(manifest.read_text(encoding='utf-8'))['dsh']['profile']))
 home=directory/'home';retired=home/'profiles/headless';init_profile(str(retired),['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@deepseek-ai/dsh-headless']);manifest=retired/'package.json';raw=json.loads(manifest.read_text(encoding='utf-8'));raw['dsh']['profile']['patchReload']='retained-extension';manifest.write_text(json.dumps(raw),encoding='utf-8');load_profile('test','headless',str(anchor),str(home))
 result.append(dict(kind='retired',profile=json.loads(manifest.read_text(encoding='utf-8'))['dsh']['profile']))
 for mode in ('base','web-app','headless','sdk-app','acp-app','sdk-minimal'):
  layers=[load_overlay_patches('test',str(ROOT/'packages/bundle/base/cordis.patch.yml'))] if mode not in ('base','sdk-minimal') else []
  layers.append(load_overlay_patches('test',str(ROOT/'packages/bundle'/mode/'cordis.patch.yml')))
  row=next((row for row in compose_entries(layers) if row.get('id')=='hmr'),None)
  result.append(dict(kind='row',mode=mode,row=None if row is None else {key:row[key] for key in ('name','disabled','config')}))
 result.append(dict(kind='templates',values={name:PROFILE_TEMPLATES[name] for name in ('acp','web','headless','sdk','sdk-minimal')}))
 return result

async def native():return observe(OUTPUT/'files/native')
if __name__=='__main__':
 probe.native=native
 probe.main('rc022_profile_hmr.mts','Retired patchReload fields remain inert unknown manifest metadata; exact shipped tuple normalization and actual YAML-owned HMR selection across official profiles.',[Path(__file__).resolve(),ROOT/'dsh/boot/profile.py',ROOT/'dsh/boot/profile_boot.py',ROOT/'dsh/cordis/profile.py',*[ROOT/'packages/bundle'/part/'cordis.patch.yml' for part in ('base','web-app','headless','sdk-app','acp-app','sdk-minimal')],ROOT/'reference/packages/boot/app-boot/lib/index.js'],prepare,plain_node=True)
