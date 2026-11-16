"""Real current manager installation/removal and request ownership journeys."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,sys,time
from pathlib import Path
data=json.loads(Path('operation.json').read_text(encoding='utf-8'));mode=data['mode'];args=sys.argv[1:]
with Path('runs.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(args)+'\\n')
if args[:3]==['config','get','registry']:print('https://registry.npmjs.org/');sys.exit(0)
if args[0]=='view':print(json.dumps(dict(name='fresh',version='1.0.0')));sys.exit(0)
manifest=json.loads(Path('package.json').read_text(encoding='utf-8'))
if args[0]=='remove':
    manifest.get('dependencies',{}).pop(args[1],None);Path('package.json').write_text(json.dumps(manifest),encoding='utf-8');print('removed');sys.exit(0)
if args[0]=='install':sys.exit(0)
if mode=='fallback' and not any(arg.startswith('--registry=') for arg in args):
    manifest['partial']='must restore';Path('package.json').write_text(json.dumps(manifest),encoding='utf-8');print('ERR_PNPM_FETCH_404 absent',file=sys.stderr);sys.exit(1)
names=['fresh','other'] if mode=='ambiguous' else ['fresh']
for name in names:
    manifest.setdefault('dependencies',{})[name]='1.0.0' if '--save-exact' in args else '^1.0.0'
    directory=Path('node_modules')/name;directory.mkdir(parents=True,exist_ok=True)
    package=dict(name=name,version='1.0.0')
    if mode!='plain':package['dsh']=dict(bundle=dict(patch='patch.yml'))
    if mode=='incompatible':package['engines']=dict(dsh='>=99.0.0')
    (directory/'package.json').write_text(json.dumps(package),encoding='utf-8')
    (directory/'patch.yml').write_text(json.dumps([dict(insert=[dict(id='fresh-row',name='cordis:active')])]),encoding='utf-8')
Path('package.json').write_text(json.dumps(manifest),encoding='utf-8');Path('pnpm-lock.yaml').write_bytes(b'changed\\r\\n')
if mode in ('cancel','waiter-cancel'):print('waiting',flush=True);time.sleep(10)
if mode=='build-blocked':print('Ignored build scripts: builder',file=sys.stderr);sys.exit(1)
print('added')
'''


def corpus():return ['startup','disabled','exact','live','fallback','plain','ambiguous','incompatible','build-blocked','approve','cancel','too-late','activation-error','invalid','repeat-live','remove-startup']


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
            home=(workspace or WORKSPACE)/'native'/mode;directory=home/'profile';directory.mkdir(parents=True)
            def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
            write(home/'package.json',dict(name='installation'));write(directory/'package.json',dict(name='profile',dependencies={},dsh=dict(profile=dict(bundles=['core']))))
            write(directory/'node_modules/core/package.json',dict(name='core',version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
            write(directory/'node_modules/core/patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=dict(lockWaitMs=0))])])
            write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[]);write(directory/'operation.json',dict(mode=mode))
            (directory/'pnpm-lock.yaml').write_bytes(b'original\r\n')
            if mode=='approve':(directory/'pnpm-workspace.yaml').write_text('allowBuilds:\n  builder: "set this to true or false"\n',encoding='utf-8')
            script=directory/'package.py';script.write_text(PROGRAM,encoding='utf-8')
            profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core'],overlays=[],packageManager=dict(command=str(Path(sys.executable).resolve()),args=[str(script)]))
            def active(ctx,config):
                if mode=='activation-error':raise RuntimeError('cannot start bundle')
                ctx.provide('installedProbe',True)
            def setup(ctx):ctx.provide('profileContext',profile);ctx.loader.builtins.update(manager=CurrentPluginManager,active=active)
            ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
            logs=[];states=[];facts=[];changed=[];too_late=[];waiting=asyncio.Event()
            def log(event):
                logs.append(event)
                if 'waiting' in event['text']:waiting.set()
            ctx.on('plugin-manager/install-log',log);ctx.on('plugin-manager/operation',lambda event:facts.append(event));ctx.on('plugin-manager/changed',lambda event:changed.append(event))
            def state(event):
                states.append(event)
                if mode=='too-late' and event['phase']=='applying':too_late.append(ctx.pluginManager.cancelInstall(mode))
            ctx.on('plugin-manager/install-state',state)
            try:
                manager=ctx.pluginManager
                if mode in ('live','repeat-live','too-late','activation-error'):
                    await ctx.plugin(TimerService)
                    from types import SimpleNamespace
                    ctx.provide('appReady',SimpleNamespace(onReady=lambda listener:(listener(),lambda:None)[1]))
                    await ctx.plugin(ConfigWatcherService,dict(root=[],ignored=[],debounce=0));await ctx.hmr.runExclusive(lambda:None)
                options=dict(requestId=mode)
                if mode=='disabled':options['enabled']=False
                if mode=='exact':options['saveExact']=True
                if mode=='approve':options['approvedBuilds']=['builder']
                promise=manager.installBundle('-invalid' if mode=='invalid' else 'fresh',options)
                wait=manager.waitForInstall(mode)
                cancellation=None
                if mode=='cancel':
                    await asyncio.wait_for(waiting.wait(),5);cancellation=await manager.cancelInstall(mode)
                result=await promise;wait_result=await wait
                steps=[result]
                if mode=='repeat-live':steps.append(await manager.installBundle('fresh',dict(requestId='repeat')))
                installed=ctx.get('installedProbe') is True
                if mode=='remove-startup':profile['startedBundles'].append('fresh')
                if mode in ('startup','live','remove-startup','disabled'):steps.append(await manager.removeBundle('fresh'))
                for _ in range(20):await asyncio.sleep(0)
                jobs=[]
                def normalize(value):
                    if isinstance(value,list):return [normalize(item) for item in value]
                    if not isinstance(value,dict):return value.replace(str(directory),'<profile>') if isinstance(value,str) else value
                    answer={key:normalize(item) for key,item in value.items() if key not in ('logPath',)}
                    if 'jobId' in answer:
                        if answer['jobId'] not in jobs:jobs.append(answer['jobId'])
                        answer['jobId']=jobs.index(answer['jobId'])
                    if mode=='activation-error' and isinstance(answer.get('error'),dict) and 'diagnostic' in answer['error']:answer['error']['diagnostic']=True
                    return answer
                rows.append(normalize(dict(name=mode,steps=steps,waitSame=wait_result==result,cancel=cancellation,tooLate=[await item for item in too_late],afterWait=await manager.waitForInstall(mode),afterCancel=await manager.cancelInstall(mode),installed=installed,removed=ctx.get('installedProbe') is None,selection=json.loads((directory/'package.json').read_text(encoding='utf-8'))['dsh']['profile']['bundles'],dependencies=json.loads((directory/'package.json').read_text(encoding='utf-8')).get('dependencies',{}),lock=(directory/'pnpm-lock.yaml').read_bytes().decode('utf-8'),pending=(await manager.inspect('fresh'))['status'] if mode=='invalid' else None,logs=logs,states=states,changed=changed,facts=[{key:value for key,value in event.items() if key not in ('id','time')} for event in facts],remotes=all(any(row['method']==name for row in remote_methods(manager)) for name in ('installBundle','removeBundle','cancelInstall','waitForInstall')))))
            finally:await ctx.fiber.dispose()
        return rows
    finally:dsh.__version__=old


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_manager_installation.mts','Real Include/Loader/HMR manager installation/removal, controlled package executable, progress and operation facts, registry fallback, refusals, build approval, request waiting/cancellation and activation. log paths and UUIDs normalized; actual activation failure diagnostic presence only.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_installation.py',ROOT/'dsh/boot/plugin_manager_current.py',ROOT/'dsh/boot/plugin_package_operations.py'],prepare=prepare)
