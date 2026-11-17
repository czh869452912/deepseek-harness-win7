import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis import Context
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.loader_current import CurrentTypertLoader
from scripts.rc022_typert_owner_probe import observe


@pytest.mark.asyncio
async def test_current_canonical_package_generated_codec_and_registration_lifetime(tmp_path):
    rows=await observe(tmp_path)
    assert [row['packages'] for row in rows]==[1,1,0,1,0]
    assert [row['strict'] for row in rows]==[True,True,False,True,False]
    assert rows[0]['value']=='native'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[False,True])
async def test_active_resolver_absence_is_cached_and_never_falls_back_to_installation(tmp_path,failure):
    name='@fixture/absent';ctx=Context();ctx.baseUrl=str(tmp_path/'entry.cjs');calls=[]
    row=SimpleNamespace(options=dict(name=name),fiber=SimpleNamespace(),disabled=False)
    ctx.provide('loader',SimpleNamespace(entries=lambda:[row],installation_module_roots=[str(tmp_path/'node_modules')],harness_plugins={name:object}))
    def lookup(*args):
        calls.append(args)
        if failure:raise RuntimeError('resolver refused')
        return None
    ctx.provide('pluginPackages',SimpleNamespace(packageOf=lookup))
    await ctx.plugin(CurrentTypertRegistry)
    try:
        await ctx.plugin(CurrentTypertLoader)
        directory=tmp_path/'node_modules'/name;directory.mkdir(parents=True)
        (directory/'package.json').write_text(json.dumps(dict(name=name,exports={'./typert':'./host.mjs'})),encoding='utf-8')
        (directory/'host.mjs').write_text('would be invalid if read',encoding='utf-8')
        ctx.emit('internal/plugin',SimpleNamespace(entry=row))
        for _ in range(10):await asyncio.sleep(0)
        assert len(calls)==1 and ctx.typert.listPackages()==[]
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_explicit_missing_package_fails_activation(tmp_path):
    ctx=Context();ctx.baseUrl=str(tmp_path/'entry.cjs')
    ctx.provide('loader',SimpleNamespace(entries=lambda:[]))
    ctx.provide('pluginPackages',SimpleNamespace(packageOf=lambda *_:None))
    await ctx.plugin(CurrentTypertRegistry)
    try:
        with pytest.raises(ValueError,match='configured package cannot be resolved'):
            await ctx.plugin(CurrentTypertLoader,dict(packages=['@fixture/missing']))
        assert ctx.typert.listPackages()==[]
    finally:await ctx.fiber.dispose()
