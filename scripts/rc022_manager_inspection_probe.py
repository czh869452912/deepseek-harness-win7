"""Current management reads over real profiles and owned executable responses."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
PROGRAM='''import json,sys,time
from pathlib import Path
data=json.loads(Path('query.json').read_text(encoding='utf-8'))
args=sys.argv[1:]
if args[:3]==['config','get','registry']:
    print(data.get('resolved','https://registry.npmjs.org/'))
    sys.exit(data.get('configExit',0))
spec=args[1]
registry=next((arg.split('=',1)[1] for arg in args if arg.startswith('--registry=')),None)
with Path('queries.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(spec=spec,registry=registry,fields=args[2:args.index('--json')]))+'\\n')
response=data.get('responses',{}).get(spec,data.get('response',{}))
if registry is None and 'primaryFailure' in data:response=data['primaryFailure']
time.sleep(response.get('delay',0))
print(response.get('raw',json.dumps(response.get('answer',dict(name='fresh',version='2.0.0',dsh=dict(bundle={}))))))
if response.get('stderr'):print(response['stderr'],file=sys.stderr)
sys.exit(response.get('exit',0))
'''


def corpus():
    cases=[]
    def add(name, method='inspect', argument='fresh', query=None, **extra):
        cases.append(dict(name=name,method=method,argument=argument,query=query or {},**extra))
    add('registries','registries',query=dict(resolved='notice\nhttps://corp.example/npm'))
    add('registry-invalid','registries',query=dict(resolved='not a URL'))
    add('registry-exit','registries',query=dict(configExit=2))
    add('invalid',argument='')
    add('known-profile',argument='installed')
    add('known-installation',argument='shipped')
    add('git',argument='https://github.com/example/plugin.git#abcdef1')
    add('tar-url',argument='https://files.example/pkg.tgz')
    for name,kind in [('local-valid','valid'),('local-array-bundle','array'),('local-no-name','no-name'),('local-no-bundle','no-bundle'),('local-broken','broken'),('local-missing','missing'),('local-known','known'),('local-unreadable','unreadable')]:
        add(name,argument='<local>',local=kind)
    add('tar-missing',argument='<tar>')
    add('registry-success',query=dict(response=dict(answer=dict(version='2.0.0',description='hello',dsh=dict(bundle={})))))
    add('registry-array',query=dict(response=dict(answer=[dict(name='old'),dict(name='last',version='2.1.0',dsh=dict(bundle=[]))])))
    add('registry-empty',query=dict(response=dict(answer=[])))
    add('registry-scalar',query=dict(response=dict(answer=42)))
    add('registry-not-bundle',query=dict(response=dict(answer=dict(name='fresh',dsh=dict(bundle=None)))))
    add('registry-json',query=dict(response=dict(raw='broken')))
    add('registry-nan',query=dict(response=dict(raw='NaN')))
    add('registry-bom',query=dict(response=dict(raw='\ufeff{"dsh":{"bundle":{}}}')))
    add('registry-ansi',query=dict(response=dict(raw='\x1b[32m{"name":"fresh","dsh":{"bundle":{}}}\x1b[0m')))
    failure=dict(exit=1,answer=dict(error=dict(code='E404',message='missing')))
    add('fallback',query=dict(primaryFailure=failure))
    add('private',query=dict(resolved='https://private.example/',response=failure))
    add('explicit-private',query=dict(response=failure),options=dict(registry='https://custom.example/'))
    add('explicit-null',options=dict(registry=None))
    add('permission-no-retry',query=dict(response=dict(exit=1,stderr='EACCES permission denied')))
    add('pre-cancel',cancel='pre')
    add('caller-cancel',query=dict(response=dict(delay=1)),cancel='later')
    add('timeout',query=dict(response=dict(delay=2)),config=dict(inspectTimeoutMs=1000))
    listing=dict(versions=['1.0.0','1.1.0','2.0.0','3.0.0-beta.1','bad','4.0.0'],time={'2.0.0':'today'},**{'dist-tags':{'latest':'4.0.0','beta':'3.0.0-beta.1'}})
    version_query=dict(responses={'installed':dict(answer=listing),'installed@4.0.0':dict(answer=dict(deprecated='old',dsh=dict(bundle={}),engines=dict(dsh='>=99.0.0'))),'installed@3.0.0-beta.1':dict(answer=dict(dsh=dict(bundle={}))), 'installed@2.0.0':dict(answer=dict(dsh=dict(bundle=None)))})
    add('versions','listVersions','installed',version_query,config=dict(versionListLimit=3,versionLookupConcurrency=2))
    add('versions-exempt','listVersions','installed',version_query,exemption=True)
    add('versions-fallback','listVersions','installed',dict(version_query,primaryFailure=failure))
    add('versions-invalid','listVersions','installed',dict(response=dict(answer={})))
    add('versions-not-updatable','listVersions','unknown')
    add('versions-git','listVersions','installed',source='git+https://github.com/example/repo.git#'+'a'*40)
    add('versions-local','listVersions','installed',source='file:../local')
    add('versions-failed-detail','listVersions','installed',dict(responses={'installed':dict(answer=listing),'installed@4.0.0':failure}),config=dict(versionLookupConcurrency=1))
    add('versions-invalid-engines','listVersions','installed',dict(responses={'installed':dict(answer=listing),'installed@4.0.0':dict(answer=dict(engines=None))}),config=dict(versionLookupConcurrency=1))
    add('versions-origin','listVersions','installed',version_query,origin='https://origin.example/')
    return cases


def normalize(value):
    if isinstance(value,list):return [normalize(item) for item in value]
    if not isinstance(value,dict):return value
    result={key:normalize(item) for key,item in value.items()}
    if isinstance(result.get('reason'),str):
        if result['reason'].startswith('no readable package.json at the path:'):result['reason']='no readable package.json at the path: <reader diagnostic>'
        if result['reason'].startswith('unreadable pnpm view output:'):result['reason']='unreadable pnpm view output: <parser diagnostic>'
    return result


async def observe(workspace=None):
    import dsh
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.core.abort import AbortController
    from dsh.typert.remote import remote_methods
    output=[];old=dsh.__version__;dsh.__version__='0.2.2-rc.3'
    try:
        for case in corpus():
            home=(workspace or WORKSPACE)/'native'/case['name'];directory=home/'profile';directory.mkdir(parents=True)
            def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
            write(home/'package.json',dict(name='installation',dependencies=dict(shipped='1.0.0')))
            write(directory/'package.json',dict(name='profile',dependencies=dict(installed=case.get('source','^1.0.0')),dsh=dict(profile=dict(bundles=['core','installed']))))
            for name in ('core','installed'):
                package=directory/'node_modules'/name
                write(package/'package.json',dict(name=name,version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
                write(package/'patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=case.get('config',{}))])] if name=='core' else [])
            write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[]);write(directory/'query.json',case['query'])
            script=directory/'package.py';script.write_text(PROGRAM,encoding='utf-8')
            argument=case['argument']
            if argument=='<local>':
                local=home/'local';kind=case['local'];argument=str(local)
                if kind!='missing':
                    local.mkdir();manifest=dict(name='local',version='1.2.3',description='local bundle',dsh=dict(bundle=[] if kind=='array' else {}))
                    if kind=='no-name':manifest.pop('name')
                    if kind=='no-bundle':manifest.pop('dsh')
                    if kind=='known':manifest['name']='installed'
                    if kind!='unreadable':write(local/'package.json',manifest)
                    if kind=='broken':(local/'package.json').write_text('{',encoding='utf-8')
            if argument=='<tar>':argument=str(home/'missing.tgz')
            if case.get('exemption'):write(directory/'compatibility.json',{})
            profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core','installed'],overlays=[],packageManager=dict(command=str(Path(sys.executable).resolve()),args=[str(script)]))
            def setup(ctx):ctx.provide('profileContext',profile);ctx.loader.builtins.update(manager=CurrentPluginManager)
            ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
            try:
                manager=ctx.pluginManager
                if case.get('exemption'):
                    await manager.setVersionExemption('installed@4.0.0','0.2.2-rc.3',True,True)
                if case.get('origin'):manager.installed_from['installed']=case['origin']
                control=AbortController();timer=None
                if case.get('cancel')=='pre':control.abort()
                if case.get('cancel')=='later':timer=asyncio.get_running_loop().call_later(.5,control.abort)
                try:result=await getattr(manager,case['method'])(*(() if case['method']=='registries' else (argument,case.get('options'),control.signal)))
                finally:
                    if timer:timer.cancel()
                queries=[json.loads(line) for line in (directory/'queries.jsonl').read_text(encoding='utf-8').splitlines()] if (directory/'queries.jsonl').exists() else []
                queries.sort(key=lambda row:(row['spec'],row['registry'] or ''))
                output.append(dict(name=case['name'],result=normalize(result),queries=queries,remote=all(any(row['method']==name for row in remote_methods(manager)) for name in ('registries','inspect','listVersions'))))
            finally:await ctx.fiber.dispose()
        return output
    finally:dsh.__version__=old


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),python=str(Path(sys.executable).resolve()),program=PROGRAM,cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_manager_inspection.mts','Real manager registry, inspect and version Remote methods over real profile bundle inventories and controlled owned child queries. Parser/OS-specific diagnostic text presence is normalized; result structure, retry boundaries, fields, compatibility, concurrency, cancellation and failure class remain exact.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_inspection.py',ROOT/'dsh/boot/plugin_manager_current.py',ROOT/'dsh/boot/plugin_package_view.py'],prepare=prepare)
