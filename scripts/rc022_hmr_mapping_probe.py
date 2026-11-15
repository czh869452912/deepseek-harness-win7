"""Keep loaded namespaces authoritative after a package export mapping moves."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ['two-active', 'disabled-shadow', 'duplicate-shadow', 'disabled-reenable']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(MODES), encoding='utf-8')
    return [path]


async def observe(directory):
    from dsh.cordis.context import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.hmr_modules import module_url
    directory.mkdir(parents=True)
    result = []
    for mode in MODES:
        owner, package = directory/mode, directory/mode/'addon'
        package.mkdir(parents=True)
        modules = owner/'node_modules'
        modules.mkdir()
        link = modules/'addon'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(package), str(link))
        else:
            link.symlink_to(package, target_is_directory=True)
        manifest = package/'package.json'
        def mapping(name):
            manifest.write_text(json.dumps(dict(name='addon', version='1.0.0', exports='./'+name+'.py')), encoding='utf-8')
        def write(name, value):
            (package/(name+'.py')).write_text('def apply(ctx, config):\n    trace = ctx.get("reloadTrace")\n'
                +'    trace.append("start:'+value+':"+config["label"])\n'
                +'    ctx.effect(lambda: lambda: trace.append("stop:'+value+':"+config["label"]))\n', encoding='utf-8')
        mapping('a')
        write('a', 'a')
        write('b', 'b')
        ctx, trace = Context(), []
        ctx.baseUrl = owner.as_uri()+'/'
        ctx.provide('reloadTrace', trace)
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, dict(root=[], debounce=0))
        loader, hmr = ctx.loader, ctx.get('hmr')
        try:
            first_id = await loader.create(dict(name='addon', config=dict(label='one')))
            await loader.await_()
            first = loader.resolve(first_id)
            old_first = first.moduleNamespace
            shadow = None
            if mode in ('disabled-shadow', 'duplicate-shadow'):
                if mode == 'duplicate-shadow':
                    await loader.create(dict(name='addon', config=dict(label='duplicate')))
                shadow = loader.resolve(await loader.create(dict(name='addon', disabled=True)))
                await loader.await_()
            if mode == 'disabled-reenable':
                await first.update(dict(disabled=True))
                await loader.await_()
            trace.clear()
            mapping('b')
            hmr._module_changed(str(manifest))
            await asyncio.sleep(.04)
            await hmr.runExclusive(lambda: None)
            result.append(dict(mode=mode, step='mapping', trace=list(trace), first_same=first.moduleNamespace is old_first))
            second = None
            if mode == 'two-active':
                second = loader.resolve(await loader.create(dict(name='addon', config=dict(label='two'))))
                await loader.await_()
            old_second = None if second is None else second.moduleNamespace
            trace.clear()
            write('a', 'a-edited')
            hmr._stashed[(package/'a.py').as_uri()] = None
            await hmr.runExclusive(lambda: hmr.partialReload())
            result.append(dict(mode=mode, step='old-source', trace=list(trace), first_same=first.moduleNamespace is old_first,
                second_same=second is None or second.moduleNamespace is old_second,
                shadow_inactive=shadow is None or shadow.fiber is None))
            if second is not None:
                trace.clear()
                write('b', 'b-edited')
                hmr._stashed[(package/'b.py').as_uri()] = None
                await hmr.runExclusive(lambda: hmr.partialReload())
                result.append(dict(mode=mode, step='new-source', trace=list(trace), shared=first.fiber.runtime is second.fiber.runtime))
            if mode == 'disabled-reenable':
                trace.clear()
                await first.update(dict(disabled=False))
                await loader.await_()
                result.append(dict(mode=mode, step='reenable', trace=list(trace)))
        finally:
            await ctx.fiber.dispose()
            for name, module in list(sys.modules.items()):
                url = module_url(module)
                if url is not None and url.startswith(owner.as_uri()+'/'):
                    sys.modules.pop(name, None)
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 15)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_hmr_mapping.mts', 'Actual junction-linked package export movement: two active same-name namespaces, disabled shadows, duplicate active namespace, disabled namespace refresh then reenable through new mapping.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_partial.py', ROOT/'dsh/cordis/hmr_dispatch.py', ROOT/'dsh/cordis/loader.py', *[ROOT/'.goose/out/rc022-prep-20261114-01/source'/path for path in ('packages/boot/hmr/src/index.ts', 'packages/boot/hmr/src/package-manifest.ts', 'packages/boot/hmr/lib/index.js', 'vendor/cordis/lib/index.js', 'vendor/loader/lib/index.js', 'vendor/timer/lib/index.js')]], prepare, node_args=('--expose-internals',), plain_node=True)
