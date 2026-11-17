import json

import pytest

from dsh.boot.plugin_packages import PluginPackages
from dsh.cordis import Context, Loader, Schema
from dsh.extensions.inspect_config_current import query_live_config
from dsh.javascript.runtime import JavaScriptRuntime
from scripts.rc022_inspect_config_probe import observe, cases


@pytest.mark.asyncio
async def test_query_contract_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'inspect-config-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())
    assert {entry['status'] for entry in rows[0]['value']['entries']}=={'tree','inactive','absent','unsupported','schema'}
    assert rows[6]['value']['nextOffset']==2
    assert rows[7]['value']['nextOffset']==5
    assert any('schema' in row.get('value',{}) for row in rows)
    assert any(row.get('error')=='package lookup failed' for row in rows)


async def mounted(tmp_path):
    ctx=Context();ctx.baseUrl=tmp_path.as_uri()+'/'
    package=tmp_path/'node_modules'/'with-schema';package.mkdir(parents=True)
    (package/'package.json').write_text('{"name":"with-schema","version":"1.0.0"}',encoding='utf-8')
    await ctx.plugin(JavaScriptRuntime)
    await ctx.plugin(PluginPackages)
    await ctx.plugin(Loader)
    def with_schema(owner,config):pass
    with_schema.Config=Schema.object({'port':Schema.number().default(80).description('Listen port.')})
    def no_config(owner,config):pass
    def foreign(owner,config):pass
    foreign.Config=lambda value:value  # callable foreign validator, not a native Schema graph
    ctx.loader.register_plugin_class('with-schema',with_schema)
    ctx.loader.register_plugin_class('no-config',no_config)
    ctx.loader.register_plugin_class('foreign',foreign)
    for options in [dict(id='schema',name='with-schema'),dict(id='absent',name='no-config'),dict(id='foreign',name='foreign'),
        dict(id='off',name='with-schema',disabled=True),dict(id='group',name='cordis:group',group=True,config=[dict(id='nested',name='no-config')])]:
        await ctx.loader.create(options)
    await ctx.loader.await_()
    return ctx,package


@pytest.mark.asyncio
async def test_actual_loader_package_scope_tree_fibers_and_schema(tmp_path):
    ctx,package=await mounted(tmp_path)
    try:
        page=await query_live_config(ctx,{'limit':100})
        directory={row['id']:row for row in page['entries']}
        assert set(directory)=={'schema','absent','foreign','off','group','nested'}
        assert {key:row['status'] for key,row in directory.items()}==dict(schema='schema',absent='absent',foreign='unsupported',off='inactive',group='tree',nested='absent')
        detail=await query_live_config(ctx,{'entry':'schema'})
        owner_base=ctx.loader.resolve('schema').parent.tree.ctx.baseUrl
        (tmp_path/'package-lookup-observations.json').write_text(json.dumps(dict(root_base=ctx.baseUrl,
            owner_base=owner_base,lookup=ctx.pluginPackages.packageOf('with-schema',owner_base),detail=detail)),encoding='utf-8')
        assert detail['packageDir']==str(package)
        assert detail['schema']['$schema']=='https://json-schema.org/draft/2020-12/schema'
        assert detail['schema']['anyOf'][0]['properties']['port']['default']==80
        assert detail['schema']['$defs']['loaderExpression']['required']==['__jsExpr']
        off=await query_live_config(ctx,{'entry':'off'})
        assert off['status']=='inactive' and off['packageDir']==str(package)
        assert 'schema' not in off
        assert 'packageDir' not in await query_live_config(ctx,{'entry':'absent'})
        await ctx.loader.resolve('schema').fiber.dispose()
        assert (await query_live_config(ctx,{'entry':'schema'}))['status']=='inactive'
        assert not ctx.jsRuntime._workers
        (tmp_path/'actual-loader-observations.json').write_text(json.dumps(dict(page=page,detail=detail,off=off)),encoding='utf-8')
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_directory_reads_eagerly_without_runtime_or_cached_snapshot():
    from types import SimpleNamespace as NS
    ctx=Context();entry=NS(id='one',options=dict(id='one',name='plugin'),subgroup=None,subtree=None,
        fiber=NS(uid=1,runtime=NS(Config=None)),disabled=False)
    ctx.provide('loader',NS(entries=lambda:iter([entry])))
    try:
        before=query_live_config(ctx)
        entry.disabled=True
        assert (await before)['entries'][0]['status']=='absent'
        assert (await query_live_config(ctx))['entries'][0]['status']=='inactive'
        assert ctx.get('jsRuntime') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_apply_failure_keeps_declared_config_visible(tmp_path):
    ctx=Context();ctx.baseUrl=tmp_path.as_uri()+'/'
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(Loader)
        def failed(owner,config):raise ValueError('expected application failure')
        failed.Config=Schema.object({'token':Schema.string()})
        ctx.loader.register_plugin_class('failed',failed)
        try:await ctx.loader.create(dict(id='failed',name='failed'))
        except Exception:pass
        entry=ctx.loader.resolve('failed')
        assert entry.fiber is not None and entry.fiber.uid is not None
        detail=await query_live_config(ctx,{'entry':'failed'})
        assert detail['status']=='schema'
        assert 'token' in detail['schema']['anyOf'][0]['properties']
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_package_lookup_retains_directory_anchor_node_modules(tmp_path):
    import os
    from dsh.boot.runtime_resolution import native_package_dir
    parent=tmp_path/'node_modules'/'dep';parent.mkdir(parents=True)
    (parent/'package.json').write_text('{"name":"dep"}',encoding='utf-8')
    assert native_package_dir(str(tmp_path)+os.sep,'dep')==str(parent)
    assert native_package_dir(str(tmp_path/'caller.js'),'dep')==str(parent)
    ctx=Context()
    try:
        packages=PluginPackages(ctx)
        assert packages.packageOf('dep',tmp_path.as_uri()+'/')['dir']==str(parent)
    finally:await ctx.fiber.dispose()
