"""Profile package mutation contracts over a controlled real executable."""
import asyncio
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,shutil,sys
from pathlib import Path
data=json.loads(Path('operation.json').read_text(encoding='utf-8'));args=sys.argv[1:]
with Path('runs.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(args)+'\\n')
if args[0]=='view':print(json.dumps(data.get('view',{})));sys.exit(0)
repair=args[0]=='install' and len(args)>1 and args[1].startswith('--')
if repair:
    sys.exit(data.get('repairExit',0))
Path('package.json').write_text(json.dumps(data['after']),encoding='utf-8')
Path('pnpm-lock.yaml').write_bytes(b'changed\\r\\n')
for name,manifest in data.get('packages',{}).items():
    directory=Path('node_modules')/name;directory.mkdir(parents=True,exist_ok=True)
    (directory/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
    (directory/'patch.yml').write_text(json.dumps(data.get('patches',{}).get(name,[])),encoding='utf-8')
for name in data.get('remove',[]):
    directory=Path('node_modules')/name
    if directory.exists():shutil.rmtree(str(directory))
print('ran')
sys.exit(data.get('exit',0))
'''


def package(name='fresh',version='1.0.0',**extra):return dict(name=name,version=version,dsh=dict(bundle=dict(patch='patch.yml')),**extra)


def corpus():
    cases=[]
    before=dict(name='profile',private=True,dependencies={},dsh=dict(profile=dict(bundles=['shipped'])))
    after=copy.deepcopy(before);after['dependencies']['fresh']='1.0.0'
    def add(name,**changes):
        row=dict(name=name,before=copy.deepcopy(before),after=copy.deepcopy(after),packages=dict(fresh=package()),options={},args=['add','fresh'])
        row.update(changes);cases.append(row)
    add('activate')
    add('inactive',options=dict(activateNewBundles=False))
    add('plain',packages=dict(fresh=dict(name='fresh',version='1.0.0')))
    add('platform',packages=dict(fresh=dict(name='fresh',version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml',platforms=['darwin' if sys.platform!='darwin' else 'win32'])))))
    add('expected',options=dict(expected=dict(name='fresh',version='1.0.0')))
    add('expected-wrong',options=dict(expected=dict(name='fresh',version='2.0.0')))
    add('expected-plain',packages=dict(fresh=dict(name='fresh',version='1.0.0')),options=dict(expected=dict(name='fresh',version='1.0.0')))
    add('expected-missing',after=copy.deepcopy(before),packages={},options=dict(expected=dict(name='fresh',version='1.0.0')))
    extra=copy.deepcopy(after);extra['dependencies']['other']='2.0.0'
    add('expected-extra',after=extra,packages=dict(fresh=package(),other=package('other','2.0.0')),options=dict(expected=dict(name='fresh',version='1.0.0')))
    add('incompatible',packages=dict(fresh=package(engines=dict(dsh='>=99.0.0'))))
    add('repair-failed',packages=dict(fresh=package(engines=dict(dsh='>=99.0.0'))),repairExit=7)
    add('without-lock',packages=dict(fresh=package(engines=dict(dsh='>=99.0.0'))),noLock=True)
    add('preflight',view=package(engines=dict(dsh='>=99.0.0')))
    add('preflight-flags',view=package(),args=['--silent','add','fresh','--registry=https://private.example/'])
    add('bad-engines',packages=dict(fresh=package(engines=None)))
    add('component',packages=dict(fresh=package(),component=package('component',engines=dict(dsh='>=99.0.0'))),patches=dict(fresh=[dict(insert=[dict(id='item',name='component')])]))
    old=copy.deepcopy(before);old['dependencies']['old']='1.0.0';old['dsh']['profile']['bundles'].append('old')
    kept=copy.deepcopy(after);kept['dependencies']['old']='1.0.0';kept['dsh']['profile']['bundles'].append('old')
    old_package=package('old',engines=dict(dsh='>=99.0.0'))
    add('untouched-bad',before=old,after=kept,beforePackages=dict(old=old_package))
    add('changed-bad',before=old,after=kept,beforePackages=dict(old=package('old')),packages=dict(fresh=package(),old=old_package))
    removed=copy.deepcopy(before)
    add('remove',before=old,after=removed,packages={},beforePackages=dict(old=package('old')),remove=['old'],args=['remove','old'])
    dev=copy.deepcopy(before);dev['devDependencies']=dict(fresh='1.0.0')
    add('dev-incompatible',after=dev,packages=dict(fresh=package(engines=dict(dsh='>=99.0.0'))))
    add('nonzero',exit=7)
    add('invalid-record',record='{}',corruptProfile=True)
    add('stale-record',record='{"pid":99999999,"grouped":false}')
    numeric=copy.deepcopy(before);numeric['dependencies']={'10':'1.0.0','2':'1.0.0'}
    add('numeric-order',after=numeric,packages={'10':package('10'),'2':package('2')},args=['add','10','2'])
    return cases


def normalize(value,directory):
    if isinstance(value,dict):return {key:normalize(item,directory) for key,item in value.items()}
    if isinstance(value,list):return [normalize(item,directory) for item in value]
    return value.replace(str(directory),'<profile>') if isinstance(value,str) else value


async def observe(workspace=None):
    import dsh
    from dsh.boot.plugin_package_operations import run_profile_pnpm
    rows=[];old=dsh.__version__;dsh.__version__='0.2.2-rc.3'
    try:
        for item in corpus():
            home=(workspace or WORKSPACE)/'native'/item['name'];directory=home/'profile';directory.mkdir(parents=True)
            def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
            write(home/'package.json',dict(name='installation'));write(directory/'package.json',item['before']);write(directory/'operation.json',item)
            for name,manifest in item.get('beforePackages',{}).items():write(directory/'node_modules'/name/'package.json',manifest);write(directory/'node_modules'/name/'patch.yml',[])
            if not item.get('noLock'):(directory/'pnpm-lock.yaml').write_bytes(b'original\r\n')
            if 'record' in item:
                (directory/'.plugin-manager').mkdir();(directory/'.plugin-manager/run.json').write_text(item['record'],encoding='utf-8')
            if item.get('corruptProfile'):(directory/'package.json').write_text('{broken',encoding='utf-8')
            script=directory/'package.py';script.write_text(PROGRAM,encoding='utf-8');output=[]
            options=dict(command=str(Path(sys.executable).resolve()),args=[str(script)],execution='service',outputBytes=16384,idleTimeoutMs=5000,onOutput=lambda text,kind:output.append(dict(text=text,kind=kind)),**item['options'])
            result=await run_profile_pnpm(dict(profile='test',dir=str(directory),cwd=str(home),home=str(home),installAnchor=str(home/'package.json')),item['args'],options)
            log=Path(result.pop('logPath')).read_bytes().decode('utf-8',errors='replace')
            runs=[json.loads(line) for line in (directory/'runs.jsonl').read_text(encoding='utf-8').splitlines()] if (directory/'runs.jsonl').exists() else []
            manifest=json.loads((directory/'package.json').read_text(encoding='utf-8')) if not item.get('corruptProfile') else 'untouched-corrupt'
            lock=(directory/'pnpm-lock.yaml').read_bytes().decode('utf-8') if (directory/'pnpm-lock.yaml').exists() else None
            # OS chunk boundaries do not change callback byte concatenation.
            streams={name:''.join(row['text'] for row in output if row['kind']==name) for name in ('stdout','stderr')}
            rows.append(normalize(dict(name=item['name'],result=result,log=log,streams=streams,runs=runs,manifest=manifest,lock=lock,recordRemoved=not (directory/'.plugin-manager/run.json').exists()),directory))
        return rows
    finally:dsh.__version__=old


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'input.json'
    path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_package_operations.mts','Actual Source profile package operations and Native service transactions over controlled real executable mutations. Preflight, expected package, direct dependencies and bundle component compatibility, repair, selection/platform and active record admission. No acquisition backend or manager Remote activation claim.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_package_operations.py',ROOT/'dsh/boot/plugin_package_run.py'],prepare=prepare)
