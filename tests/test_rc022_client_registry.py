import builtins
import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context,Loader
from dsh.boot.plugin_packages import PluginPackages
from dsh.boot.runtime_resolution import create_runtime_resolution
from dsh.host.client_modules.current import CurrentClientModuleRegistry,CurrentClientModulesPlugin
from scripts.rc022_client_registry_probe import prepare,observe


@pytest.mark.asyncio
async def test_current_client_graph_restart_observations(tmp_path):
    prepare(tmp_path);rows=await observe(tmp_path/'files')
    (tmp_path/'client-registry-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    by_stage={row['stage']:row for row in rows}
    assert len(rows)==10
    assert by_stage['initial']['graph']==by_stage['unchanged']['graph']
    assert by_stage['unchanged']['notifications']==0
    assert by_stage['initial']['graph']['entries'][0]['rev']!=by_stage['export-replaced']['graph']['entries'][0]['rev']
    assert by_stage['metadata-replaced']['graph']['entries'][0]['external']==['fixture-dependency']
    assert not by_stage['declaration-removed']['graph']['entries']
    assert by_stage['declaration-added']['graph']['entries']
    assert by_stage['unchanged-rebuilt']['graphSame']


@pytest.mark.asyncio
async def test_current_client_manifest_comes_from_runtime_package_router(tmp_path,monkeypatch):
    installation=tmp_path/'installation';installation.mkdir();name='@fixture/current-client'
    anchor=installation/'package.json';anchor.write_text(json.dumps(dict(name='installation',dependencies={name:'*'})),encoding='utf-8')
    directory=installation/'node_modules'/name;directory.mkdir(parents=True)
    manifest=dict(name=name,main='index.py',exports={'.':'./index.py','./client':'./client.js'},dsh=dict(client=dict(platform='web')))
    (directory/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
    (directory/'index.py').write_text('def apply(ctx,config=None):\n    pass\n',encoding='utf-8')
    (directory/'client.js').write_text('module.exports={value:1};',encoding='utf-8')
    home=tmp_path/'home';profile=home/'profiles'/'web';profile.mkdir(parents=True)
    resolution=await create_runtime_resolution(dict(installAnchor=str(anchor),home=str(home)))
    ctx=Context();ctx.baseUrl=profile.as_uri()+'/'
    try:
        packages=PluginPackages(ctx,dict(resolution=resolution));await ctx.plugin(Loader)
        # An installed Python implementation can be a mapped provider; its
        # browser bundle must follow the runtime package router, not that class.
        ctx.loader.harness_plugins[name]=lambda ctx,config:None
        await ctx.loader.create(dict(id='client',name=name))
        fiber=ctx.plugin(CurrentClientModulesPlugin);await fiber;registry=ctx.get('clientModules')
        assert registry.locate(name,ctx.baseUrl)==str(directory/'package.json')
        assert registry.client_path(name)==str(directory/'client.js')
        assert registry.graph()['entries'][0]['id']==name
        old=registry.graph()
        original=builtins.open;reads=[]
        def tracked(path,*args,**kwargs):
            if str(path)==str(directory/'client.js'):reads.append(str(path))
            return original(path,*args,**kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(builtins,'open',tracked)
            registry.dirty[name]=None;registry.reconcile(activation=True)
            assert registry.rebuilt(name)==old['entries'][0]['rev']
        assert not reads
        assert registry.graph() is old
        assert packages.packageOf(name,ctx.baseUrl)['dir']==str(directory)
        manifest['exports']['./client']='./next.js'
        (directory/'next.js').write_text('module.exports={value:200};',encoding='utf-8')
        (directory/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
        registry.dirty[name]=None;registry.reconcile(activation=True)
        assert registry.client_path(name)==str(directory/'next.js')
        assert registry.graph()['entries'][0]['rev']!=old['entries'][0]['rev']
        await fiber.dispose();assert ctx.get('clientModules') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_registry_frozen_roster_failure_consumes_batch(tmp_path,monkeypatch):
    prepare(tmp_path);ctx=Context();scans=[];entries=[]
    def roster():scans.append(True);return iter(entries)
    ctx.provide('loader',NS(entries=roster))
    try:
        registry=CurrentClientModuleRegistry(ctx);scans.clear();warnings=[]
        registry.reconcile();assert not scans
        def broken():raise ValueError('roster failed')
        ctx.get('loader').entries=broken;registry.dirty['fixture-client']=None
        monkeypatch.setattr(registry,'_log_warn',lambda error:warnings.append(str(error)))
        graph=registry.graph();registry.reconcile()
        assert registry.graph() is graph and not registry.dirty and warnings==['roster failed']
    finally:await ctx.fiber.dispose()
