import asyncio
import json
import sys
from contextlib import asynccontextmanager

import pytest

from scripts.rc022_hmr_partial_probe import observe


@asynccontextmanager
async def runtime(directory):
    from dsh.cordis.context import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.hmr_modules import module_url
    ctx = Context()
    ctx.baseUrl = directory.as_uri()+'/'
    trace = []
    ctx.provide('reloadTrace', trace)
    await ctx.plugin(Loader)
    await ctx.plugin(TimerService)
    await ctx.plugin(ConfigWatcherService, dict(root=[]))
    try:
        yield ctx, ctx.get('hmr'), trace
    finally:
        await ctx.fiber.dispose()
        for name, module in list(sys.modules.items()):
            url = module_url(module)
            if url is not None and url.startswith(directory.as_uri()+'/'):
                sys.modules.pop(name, None)


@pytest.mark.asyncio
async def test_partial_replacement_preserves_config_and_restores_failed_generations(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'module-generations'), 25)
    by_mode = {row['mode']:row for row in rows}
    assert by_mode['upgrade']['trace'] == ['stop:1:initial', 'start:2:initial']
    assert by_mode['config']['trace'] == ['stop:1:initial', 'start:2:latest']
    assert by_mode['shared']['trace'] == ['stop:1:initial', 'stop:1:other', 'start:2:initial', 'start:2:other']
    assert by_mode['helper']['trace'] == ['stop:1:initial', 'start:2:initial']
    assert by_mode['syntax']['trace'] == []
    assert by_mode['syntax']['cached_old'] and by_mode['syntax']['same']
    assert by_mode['activation']['failed'] and by_mode['activation']['cached_old']
    assert by_mode['activation']['trace'] == ['stop:1:initial', 'start:2:initial', 'start:1:initial']
    for mode in ('syntax', 'activation'):
        assert by_mode[mode+'-recovered']['trace'] == ['stop:1:initial', 'start:3:initial']
        assert not by_mode[mode+'-recovered']['namespace_same']
    assert by_mode['disabled']['trace'] == [] and not by_mode['disabled']['active']
    assert by_mode['removed']['trace'] == [] and not by_mode['removed']['active']
    assert by_mode['unchanged']['same'] and by_mode['unchanged']['trace'] == []


@pytest.mark.asyncio
async def test_native_explicit_exports_share_one_fresh_module_generation(tmp_path):
    source = tmp_path/'exports.py'
    def write(value):
        source.write_text('\n'.join('class '+name+':\n    def apply(self, ctx, config):\n        ctx.get("reloadTrace").append("'+name+':'+str(value)+'")\n' for name in ('First', 'Second')), encoding='utf-8')
    write(1)
    async with runtime(tmp_path) as (ctx, hmr, trace):
        ids = [await ctx.loader.create(dict(name=str(source)+':'+name)) for name in ('First', 'Second')]
        await ctx.loader.await_()
        before = [ctx.loader.resolve(key).moduleNamespace for key in ids]
        trace.clear()
        write(2)
        hmr._stashed[source.as_uri()] = None
        await hmr.runExclusive(lambda: hmr.partialReload())
        assert trace == ['First:2', 'Second:2']
        after = [ctx.loader.resolve(key).moduleNamespace for key in ids]
        assert all(current is not previous for current, previous in zip(after, before))
        assert after[0].__module__ == after[1].__module__
        assert getattr(sys.modules[after[0].__module__], 'First') is after[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('installed', [False, True])
async def test_descriptor_relative_imports_keep_their_package_context(tmp_path, installed):
    package = tmp_path/('node_modules/relative-plugin' if installed else 'relative-plugin')
    package.mkdir(parents=True)
    (package/'package.json').write_text(json.dumps(dict(name='relative-plugin', version='1.0.0', dsh=dict(bundle=dict(patch='patch.json'), python=dict(apiVersion=1, sourceRoot='src', entry='host:Plugin', minPythonVersion=[3,8,10], minHostVersion=[0,1,0], dependencies=[])))), encoding='utf-8')
    (package/'patch.json').write_text('[]', encoding='utf-8')
    source = package/'src'
    source.mkdir()
    (source/'helper.py').write_text('value = 1\n', encoding='utf-8')
    host = source/'host.py'
    host.write_text('from .helper import value\nclass Plugin:\n    def apply(self, ctx, config):\n        ctx.get("reloadTrace").append(value)\n', encoding='utf-8')
    async with runtime(tmp_path) as (ctx, hmr, trace):
        key = await ctx.loader.create(dict(name='relative-plugin' if installed else str(package/'package.json')))
        await ctx.loader.await_()
        assert trace == [1]
        trace.clear()
        (source/'helper.py').write_text('value = 2\n', encoding='utf-8')
        hmr._stashed[(source/'helper.py').as_uri()] = None
        await hmr.runExclusive(lambda: hmr.partialReload())
        # Root HMR excludes node_modules, matching upstream. Installed package
        # upgrades belong to profile reconciliation's separate replacement plan.
        assert trace == ([] if installed else [2])
        assert ctx.loader.resolve(key).fiber.uid is not None


@pytest.mark.asyncio
async def test_later_failure_retires_shared_replacement_once_and_restores_both_modules(tmp_path):
    first, second = tmp_path/'shared.py', tmp_path/'failing.py'
    def write(path, value, failed=False):
        path.write_text('def apply(ctx, config):\n    trace = ctx.get("reloadTrace")\n    trace.append("start:'+str(value)+':"+config["label"])\n'
                        +('    raise RuntimeError("later failed")\n' if failed else '    ctx.effect(lambda: lambda: trace.append("stop:'+str(value)+':"+config["label"]))\n'), encoding='utf-8')
    write(first, 1)
    write(second, 1)
    async with runtime(tmp_path) as (ctx, hmr, trace):
        ids = [await ctx.loader.create(dict(name=str(path), config=dict(label=label))) for path, label in [(first, 'one'), (first, 'two'), (second, 'last')]]
        await ctx.loader.await_()
        namespaces = [ctx.loader.resolve(key).moduleNamespace for key in ids]
        trace.clear()
        write(first, 2)
        write(second, 2, True)
        hmr._stashed.update(dict.fromkeys([first.as_uri(), second.as_uri()]))
        with pytest.raises(RuntimeError, match='later failed'):
            await hmr.runExclusive(lambda: hmr.partialReload())
        assert trace.count('stop:2:one') == trace.count('stop:2:two') == 1
        assert all(ctx.loader.resolve(key).moduleNamespace is namespace for key, namespace in zip(ids, namespaces))
        assert ctx.loader.internal.loadCache[first.as_uri()] is namespaces[0]
        assert ctx.loader.internal.loadCache[second.as_uri()] is namespaces[-1]
        assert all(ctx.loader.resolve(key).fiber.uid is not None for key in ids)
