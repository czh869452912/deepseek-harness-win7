"""Actual Source/current manager update, activation and restoration journeys."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,sys,time,shutil
from pathlib import Path
mode=json.loads(Path('operation.json').read_text(encoding='utf-8'))['mode'];args=sys.argv[1:]
with Path('runs.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(args)+'\\n')
if args[:3]==['config','get','registry']:print('https://registry.npmjs.org/');sys.exit(0)
if args[0]=='view':
    package=dict(name='fresh',version='2.0.0',dsh=dict(bundle=dict(patch='patch.yml')))
    if mode=='preflight-plain':package.pop('dsh')
    if mode=='preflight-incompatible':package['engines']=dict(dsh='>=99.0.0')
    if mode=='bad-engines':package['engines']=dict(dsh='not a range')
    if mode=='lookup-failure':print('ERR_PNPM_FETCH_403 forbidden',file=sys.stderr);sys.exit(1)
    print(json.dumps(package));sys.exit(0)
manifest=json.loads(Path('package.json').read_text(encoding='utf-8'))
if args[0]=='remove':
    if mode=='removal-fails':print('cannot remove',file=sys.stderr);sys.exit(1)
    manifest.get('dependencies',{}).pop(args[1],None);Path('package.json').write_text(json.dumps(manifest),encoding='utf-8');shutil.rmtree('node_modules/fresh',ignore_errors=True);print('removed');sys.exit(0)
if args[0]=='install':sys.exit(0)
version=args[1].rsplit('@',1)[-1];target=version=='2.0.0'
if mode in ('target-fails','restore-fails') and (target or mode=='restore-fails'):print('ERR_PNPM_FETCH_404 absent',file=sys.stderr);sys.exit(1)
if mode=='cancel' and target:print('waiting',flush=True);time.sleep(10)
names=['other'] if mode=='wrong-name' and target else ['fresh','other'] if mode=='extra-dependency' and target else ['fresh']
if mode=='wrong-version' and target:version='1.5.0'
for name in names:
    manifest.setdefault('dependencies',{})[name]=version
    directory=Path('node_modules')/name;directory.mkdir(parents=True,exist_ok=True)
    package=dict(name=name,version=version,dsh=dict(bundle=dict(patch='patch.yml')))
    if mode=='plain-installed' and target:package.pop('dsh')
    if mode=='incompatible-installed' and target:package['engines']=dict(dsh='>=99.0.0')
    (directory/'package.json').write_text(json.dumps(package),encoding='utf-8')
    (directory/'patch.yml').write_text(json.dumps([dict(insert=[dict(id='fresh-row',name='cordis:active',config=dict(version=version))])]),encoding='utf-8')
Path('package.json').write_text(json.dumps(manifest),encoding='utf-8');Path('pnpm-lock.yaml').write_bytes(('lock '+version+'\\r\\n').encode('utf-8'));print('added '+version)
'''


def corpus():return ['live','startup','disabled','target-fails','restore-fails','activation-error','wrong-version','wrong-name','extra-dependency','plain-installed','incompatible-installed','preflight-plain','preflight-incompatible','bad-engines','lookup-failure','removal-fails','cancel','invalid-version','same-version','unknown','registry-spec','git-missing','git-branch','git-other']


async def observe(workspace=None):
    import dsh
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    from dsh.typert.remote import remote_methods
    rows=[];old=dsh.__version__;dsh.__version__='0.2.2-rc.3'
    try:
        for mode in corpus():
            home=(workspace or WORKSPACE)/'native'/mode;directory=home/'profile'
            def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
            source='git+https://example.invalid/repository.git#'+'a'*40 if mode.startswith('git-') else '1.0.0'
            write(home/'package.json',dict(name='installation'));write(directory/'package.json',dict(name='profile',dependencies=dict(fresh=source),dsh=dict(profile=dict(bundles=['core']+([] if mode=='disabled' else ['fresh'])))))
            for name in ('core','fresh'):
                write(directory/('node_modules/'+name+'/package.json'),dict(name=name,version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
            write(directory/'node_modules/core/patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=dict(lockWaitMs=0))])])
            write(directory/'node_modules/fresh/patch.yml',[dict(insert=[dict(id='fresh-row',name='cordis:active',config=dict(version='1.0.0'))])])
            write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[]);write(directory/'operation.json',dict(mode=mode))
            (directory/'pnpm-lock.yaml').write_bytes(b'original\r\n');script=directory/'package.py';script.write_text(PROGRAM,encoding='utf-8')
            profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core'],overlays=[],packageManager=dict(command=str(Path(sys.executable).resolve()),args=[str(script)]))
            def active(ctx,config):
                if mode=='activation-error' and config['version']=='2.0.0':raise RuntimeError('cannot start bundle')
                ctx.provide('installedProbe',config['version'])
            def setup(ctx):ctx.provide('profileContext',profile);ctx.loader.builtins.update(manager=CurrentPluginManager,active=active)
            ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
            logs=[];states=[];updates=[];facts=[];changed=[];waiting=asyncio.Event()
            def log(event):
                logs.append(event)
                if 'waiting' in event['text']:waiting.set()
            ctx.on('plugin-manager/install-log',log);ctx.on('plugin-manager/install-state',lambda event:states.append(event));ctx.on('plugin-manager/update-state',lambda event:updates.append(event));ctx.on('plugin-manager/operation',lambda event:facts.append(event));ctx.on('plugin-manager/changed',lambda event:changed.append(event))
            try:
                manager=ctx.pluginManager
                if mode!='startup':
                    await ctx.plugin(TimerService);ctx.provide('appReady',SimpleNamespace(onReady=lambda listener:(listener(),lambda:None)[1]))
                    await ctx.plugin(ConfigWatcherService,dict(root=[],ignored=[],debounce=0));await ctx.hmr.runExclusive(lambda:None)
                options=dict(requestId=mode)
                if mode=='registry-spec':options['spec']='fresh@2.0.0'
                if mode=='git-branch':options['spec']='git+https://example.invalid/repository.git#main'
                if mode=='git-other':options['spec']='git+https://example.invalid/other.git#'+'b'*40
                version='bad' if mode=='invalid-version' else '1.0.0' if mode=='same-version' else '2.0.0'
                promise=manager.updateBundle('missing' if mode=='unknown' else 'fresh',version,options);cancellation=None
                if mode=='cancel':await asyncio.wait_for(waiting.wait(),5);cancellation=await manager.cancelInstall(mode)
                result=await promise
                for _ in range(20):await asyncio.sleep(0)
                jobs=[]
                def normalize(value):
                    if isinstance(value,list):return [normalize(item) for item in value]
                    if not isinstance(value,dict):return value.replace(str(directory),'<profile>') if isinstance(value,str) else value
                    answer={key:normalize(item) for key,item in value.items() if key!='logPath'}
                    if 'jobId' in answer:
                        if answer['jobId'] not in jobs:jobs.append(answer['jobId'])
                        answer['jobId']=jobs.index(answer['jobId'])
                    if mode=='activation-error' and isinstance(answer.get('error'),dict) and 'diagnostic' in answer['error']:answer['error']['diagnostic']=True
                    return answer
                manifest=json.loads((directory/'package.json').read_text(encoding='utf-8'))
                rows.append(normalize(dict(name=mode,result=result,cancel=cancellation,probe=ctx.get('installedProbe'),selection=manifest['dsh']['profile']['bundles'],dependencies=manifest.get('dependencies',{}),lock=(directory/'pnpm-lock.yaml').read_bytes().decode('utf-8'),logs=logs,states=states,updates=updates,changed=changed,facts=[{key:value for key,value in event.items() if key not in ('id','time')} for event in facts],commands=[json.loads(line) for line in (directory/'runs.jsonl').read_text(encoding='utf-8').splitlines()] if (directory/'runs.jsonl').exists() else [],remote=any(row['method']=='updateBundle' for row in remote_methods(manager)))))
            finally:await ctx.fiber.dispose()
        return rows
    finally:dsh.__version__=old


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_manager_update.mts','Actual manager registry update/refusal, remove/install/restore including cancellation and real HMR activation, exact expected postconditions; Git origin plan refusals. Paths/UUID normalized, activation diagnostic presence only.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_update.py',ROOT/'dsh/boot/plugin_manager_current.py'],prepare=prepare)
