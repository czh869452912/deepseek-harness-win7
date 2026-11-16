"""Real manager queries through the Python executable adapter with empty PATH."""
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_python_package_query_probe import RegistryFixture
from dsh.boot.python_package_cli import package_command
FIXTURE=None
WORKSPACE=None


async def observe(workspace=None):
    import dsh
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    fixture=FIXTURE if workspace is None else RegistryFixture();home=(workspace or WORKSPACE)/'native';directory=home/'profile';old=dsh.__version__;dsh.__version__='0.2.2-rc.3'
    def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    write(home/'package.json',dict(name='installation'));write(directory/'package.json',dict(name='profile',dependencies=dict(fresh='1.0.0'),dsh=dict(profile=dict(bundles=['core']))))
    for name in ['core','fresh']:write(directory/('node_modules/'+name+'/package.json'),dict(name=name,version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
    write(directory/'node_modules/core/patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager',config=dict(lockWaitMs=0,fallbackRegistries=[]))])]);write(directory/'node_modules/fresh/patch.yml',[])
    write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[]);blank=directory/'npmrc';blank.write_text('',encoding='utf-8')
    command=package_command(dict(PATH='',NPM_CONFIG_USERCONFIG=str(blank),npm_config_registry=fixture.url,NO_PROXY='127.0.0.1,localhost'))
    profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core'],overlays=[],packageManager=command)
    def setup(ctx):ctx.provide('profileContext',profile);ctx.loader.builtins['manager']=CurrentPluginManager
    ctx=None
    try:
        ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup);manager=ctx.pluginManager
        rows=[dict(name='registries',result=await manager.registries())]
        for name,spec in [('inspect','timed'),('scope','@scope/pkg'),('alias','alias@npm:@scope/pkg@^1.0.0'),('known','fresh'),('missing','timed@8.0.0')]:rows.append(dict(name=name,result=await manager.inspect(spec)))
        rows.append(dict(name='versions',result=await manager.listVersions('fresh')))
        def normalize(value):
            if isinstance(value,list):return [normalize(item) for item in value]
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            return value.replace(fixture.url,'<registry>/') if isinstance(value,str) else value
        return normalize(rows)
    finally:
        if ctx is not None:await ctx.fiber.dispose()
        if workspace is not None:fixture.close()
        dsh.__version__=old


def prepare(output):
    global FIXTURE,WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();FIXTURE=RegistryFixture();path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),registry=FIXTURE.url,command=package_command())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_python_package_command.mts','Source/current manager registries/inspect/listVersions invoke actual Python-only metadata adapter with empty PATH against a loopback registry; no pnpm command substitution or fixture package program.',[Path(__file__).resolve(),ROOT/'dsh/boot/python_package_cli.py',ROOT/'dsh/boot/python_package_query.py'],prepare=prepare)
    finally:
        if FIXTURE is not None:FIXTURE.close()
