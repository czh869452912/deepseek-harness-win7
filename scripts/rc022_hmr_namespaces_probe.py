"""Observe aliases sharing a runtime and diverging across source generations."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ['aliases', 'split', 'split-unmanaged', 'retained-installed']


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
        owner = directory/mode
        owner.mkdir()
        helper = owner/('_rc022_namespace_'+mode.replace('-', '_')+'.py')
        first = owner/'first.py'
        second = owner/('node_modules/retained/second.py' if mode == 'retained-installed' else 'second.py')
        second.parent.mkdir(parents=True, exist_ok=True)
        def write(value):
            source = ''
            for name in ('shared', 'left', 'right'):
                source += ('def '+name+'(ctx, config):\n    trace = ctx.get("reloadTrace")\n'
                    +'    trace.append("start:'+name+':'+str(value)+':"+config["label"])\n'
                    +'    ctx.effect(lambda: lambda: trace.append("stop:'+name+':'+str(value)+':"+config["label"]))\n')
            helper.write_text(source, encoding='utf-8')
        write(1)
        for path in (first, second):
            path.write_text('from '+helper.stem+' import shared as apply\n', encoding='utf-8')
        ctx, trace = Context(), []
        ctx.baseUrl = owner.as_uri()+'/'
        ctx.provide('reloadTrace', trace)
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, dict(root=[]))
        loader, hmr = ctx.loader, ctx.get('hmr')
        sys.path.insert(0, str(owner))
        try:
            ids = [await loader.create(dict(name=str(path), config=dict(label=label))) for path, label in [(first, 'one'), (second, 'two')]]
            await loader.await_()
            entries = [loader.resolve(key) for key in ids]
            before = [entry.moduleNamespace for entry in entries]
            if mode == 'split-unmanaged':
                await ctx.plugin(before[0], dict(label='unmanaged'))
            trace.clear()
            events = []
            ctx.on('hmr/reload', lambda rows: events.append(len(rows)))
            write(2)
            if mode.startswith('split'):
                for path, name in [(first, 'left'), (second, 'right')]:
                    path.write_text('from '+helper.stem+' import '+name+' as apply\n', encoding='utf-8')
            hmr._stashed[helper.as_uri()] = None
            failed = False
            try:
                await hmr.runExclusive(lambda: hmr.partialReload())
            except RuntimeError as error:
                assert 'ambiguous' in str(error)
                failed = True
            result.append(dict(mode=mode, failed=failed, trace=list(trace),
                namespace_same=[entry.moduleNamespace is namespace for entry, namespace in zip(entries, before)],
                shared=entries[0].fiber.runtime is entries[1].fiber.runtime, events=events,
                cached_same=[loader.internal.loadCache.get(path.as_uri()) is namespace for path, namespace in zip((first, second), before)],
                old_instances=len(getattr(ctx.registry.get(before[0]), 'fibers', ()))))
        finally:
            await ctx.fiber.dispose()
            sys.path.remove(str(owner))
            for name, module in list(sys.modules.items()):
                url = module_url(module)
                if url is not None and url.startswith(owner.as_uri()+'/'):
                    sys.modules.pop(name, None)
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 15)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_hmr_namespaces.mts', 'Actual re-exported namespaces sharing one runtime; coherent replacement, split implementations, ambiguous unmanaged rollback and retained node_modules namespace.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_partial.py', ROOT/'dsh/cordis/hmr.py', ROOT/'reference/packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
