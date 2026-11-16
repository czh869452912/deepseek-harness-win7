"""Manager bundle projection and selection over real profile/package files."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    return ['ordinary','startup','shipped','platform','incompatible','exempted','broken-patch','protected-broken','invalid-listing','missing-selected','not-bundle','offered-installed','source-forms','null-version']


async def observe(workspace=None):
    import dsh
    from dsh.cordis import Context
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.boot.plugin_bundle_metadata import OFFICIAL_CATALOG, OFFICIAL_DATA
    rows=[];original_version=dsh.__version__;dsh.__version__='0.2.2-rc.3'
    try:
        for mode in corpus():
            ctx=Context();home=(workspace or WORKSPACE)/'native'/mode;directory=home/'profile';directory.mkdir(parents=True);calls=[]
            def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
            def package(name,extra=None,root=None):
                package_dir=(root or directory)/'node_modules'/name
                manifest=dict(name=name,version='1.0.0',description='Local '+name,dsh=dict(bundle=dict(patch='cordis.patch.yml')))
                if extra:manifest.update(extra)
                write(package_dir/'package.json',manifest)
                write(package_dir/'cordis.patch.yml',[dict(insert=[dict(id=name,name='cordis:active')]),dict(id='foreign',disabled=True)])
                return package_dir
            anchor=home/'package.json';write(anchor,dict(name='installation',dependencies=dict(extra='1.0.0') if mode=='shipped' else {}))
            core=package('core');write(core/'cordis.patch.yml',[dict(insert=[dict(id='manager',name='@deepseek-ai/dsh-plugin-manager')])])
            extra=package('extra');selected=['core','extra'];dependencies=dict(extra='^1.0.0',ordinary='1.0.0')
            write(directory/'node_modules/ordinary/package.json',dict(name='ordinary',version='1.0.0'))
            if mode=='shipped':package('extra',dict(version='9.0.0'),home)
            manifest=json.loads((extra/'package.json').read_text(encoding='utf-8'))
            if mode=='platform':manifest['dsh']['bundle']['platforms']=['darwin']
            if mode in ('incompatible','exempted'):manifest['engines']=dict(dsh='>=99.0.0')
            if mode=='exempted':write(directory/'compatibility.json',{'extra@1.0.0':['0.2.2-rc.3']})
            if mode=='invalid-listing':manifest['dsh']['bundle']['listedByDefault']='false'
            if mode=='null-version':manifest.update(version=None,description=None)
            write(extra/'package.json',manifest)
            if mode=='missing-selected':selected.append('missing')
            if mode=='not-bundle':selected.append('ordinary')
            if mode=='offered-installed':
                name=OFFICIAL_CATALOG[0]['packageName'];package(name);dependencies[name]='1.0.0'
            if mode=='source-forms':
                for name,spec in [('git-pinned','github:a/b#'+'a'*40),('git-branch','github:a/b#main'),('alias','npm:other@1'),('local','file:../plugin'),('tag','latest')]:package(name);dependencies[name]=spec
            write(directory/'package.json',dict(name='profile',dependencies=dependencies,dsh=dict(profile=dict(bundles=selected))))
            write(directory/'cordis.patch.yml',[])
            profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(anchor),cwd=str(home),home=str(home),startedBundles=list(selected),overlays=[])
            parent=NS(tree=NS(ctx=NS(baseUrl='file:///C:/live/')))
            entries=[NS(id='include:extra',options=dict(id='extra',name='cordis:active'),parent=parent)]
            ctx.set_service('loader',NS(entries=lambda:entries));ctx.set_service('profileContext',profile)
            async def refresh():calls.append('refresh')
            ctx.set_service('pluginPackages',NS(metaOf=lambda name,base:dict(title='row '+name),packageOf=lambda *args:None,refresh=refresh))
            if mode!='startup':
                async def exclusive(operation):return await operation()
                async def reload(required):calls.append(dict(reload=list(required)));return dict(warnings=[],pending=[])
                ctx.set_service('hmr',NS(runExclusive=exclusive,reconcileProfile=reload))
            try:
                await ctx.plugin(CurrentPluginManager)
                if mode in ('broken-patch','protected-broken'):(extra if mode=='broken-patch' else core).joinpath('cordis.patch.yml').write_text('[invalid',encoding='utf-8')
                first=await ctx.pluginManager.listBundles();steps=[]
                for name,enabled in [('extra',False),('extra',False),('extra',True),('core',False)]:
                    value=await ctx.pluginManager.setBundleEnabled(name,enabled)
                    steps.append(dict(result=value,selected=json.loads((directory/'package.json').read_text(encoding='utf-8'))['dsh']['profile']['bundles']))
                second=await ctx.pluginManager.listBundles()
                def normalize(value):
                    if isinstance(value,list):return [normalize(item) for item in value]
                    if isinstance(value,dict):
                        result={key:normalize(item) for key,item in value.items()}
                        if 'diagnostic' in result:result['diagnostic']=bool(result['diagnostic'])
                        if isinstance(result.get('error'),str) and result['error']!='dsh.bundle.listedByDefault must be a boolean':result['error']=bool(result['error'])
                        return result
                    return value.replace(str(directory),'<profile>').replace(str(home),'<home>') if isinstance(value,str) else value
                rows.append(normalize(dict(name=mode,first=first,steps=steps,second=second,calls=calls)))
            finally:await ctx.fiber.dispose()
        return [dict(data=OFFICIAL_DATA)] + rows
    finally:dsh.__version__=original_version


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_bundle_inventory.mts','Actual PluginManager bundle list/select over profile and installation packages; official data and catalog targets, ownership, declared rows/overrides, local metadata, update eligibility from registry/Git/local sources, platform/compatibility/exemptions, invalid display metadata and broken declarations, retained manager protection, no-op selection, HMR/restart outcomes. Normalize only runtime diagnostic presence and owned fixture roots.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_manager_current.py',ROOT/'dsh/boot/plugin_bundle_metadata.py',ROOT/'dsh/boot/official_bundles_current.json',ROOT/'scripts/extract_rc022_official_catalog.mts'],prepare=prepare)
