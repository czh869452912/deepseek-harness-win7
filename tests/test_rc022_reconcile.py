import asyncio
import contextlib
import io
import json
import pytest
from dsh.boot import boot, reconcile_profile_patches
from dsh.cordis import Context
from scripts import rc022_reconcile_probe as probe


def test_reconciliation_preserves_old_failures_but_rejects_new_ones(tmp_path):
    probe.OUTPUT=tmp_path
    result={row['mode']:row for row in asyncio.run(probe.native())}
    assert len(result)==11
    for mode in ('changed','required','new','required-pending','missing-changed'):
        assert result[mode]['fatal'] and result[mode]['events']==[]
    for mode in ('unchanged','pending','missing'):
        assert not result[mode]['fatal'] and result[mode]['warnings']==1 and result[mode]['events']==[[]]
        assert result[mode]['same_entry'] and result[mode]['same_fiber']
    for mode in ('remove','held','dispose-error'):
        assert result[mode]['removed'] and result[mode]['events']==[[]]
    assert result['held']['settled_before'] is False


@pytest.mark.asyncio
async def test_reconciliation_requires_the_launcher_root():
    ctx=Context()
    try:
        with pytest.raises(RuntimeError,match='requires the root Include entry'):
            await reconcile_profile_patches(ctx,[],'test')
        from dsh.cordis.loader import Loader
        await ctx.plugin(Loader)
        with pytest.raises(RuntimeError,match='requires the root Include entry'):
            await reconcile_profile_patches(ctx,[],'test')
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_pending_service_becomes_active_without_a_new_entry(tmp_path):
    path=tmp_path/'root.json';path.write_text('[]',encoding='utf-8')
    row={'id':'waiting','name':'cordis:waiting'}
    def setup(ctx):
        def waiting(owner,config):pass
        waiting.inject=['newProvider'];ctx.loader.builtins['waiting']=waiting
    with contextlib.redirect_stderr(io.StringIO()):ctx=await boot('test',str(path),[{'insert':[row]}],setup)
    try:
        entry=next(row for row in ctx.loader.entries() if row.options['id']=='waiting')
        fiber=entry.fiber
        ctx.provide('newProvider',{})
        assert await reconcile_profile_patches(ctx,[{'insert':[row]}],'test')==[]
        assert entry.fiber is fiber and fiber.state==2
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_compatibility_decision_applies_to_every_reconciled_layer(tmp_path):
    path=tmp_path/'root.json';path.write_text('[]',encoding='utf-8')
    package=tmp_path/'node_modules'/'denied';package.mkdir(parents=True)
    (package/'package.json').write_text(json.dumps(dict(name='denied',version='1.0.0',engines=dict(dsh='^99'))),encoding='utf-8')
    (package/'index.py').write_text('raise RuntimeError("must not import")',encoding='utf-8')
    patch=[{'insert':[{'id':'denied','name':'denied'}]}]
    def setup(ctx):ctx.provide('profileContext',dict(dir=str(tmp_path)))
    ctx=await boot('test',str(path),[],setup)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            assert await reconcile_profile_patches(ctx,patch,'test')==[]
        entry=next(row for row in ctx.loader.entries() if row.options['id']=='denied')
        assert entry.disabled and entry.fiber is None
        assert patch==[{'insert':[{'id':'denied','name':'denied'}]}]
        assert path.read_text(encoding='utf-8')=='[]'
    finally:await ctx.fiber.dispose()
