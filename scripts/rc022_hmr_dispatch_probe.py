"""Observe the real HMR service's root-event batch classification."""
import asyncio
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text('{}', encoding='utf-8')
    return [path]


async def observe(directory):
    from dsh.cordis.context import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    from dsh.cordis.hmr import ConfigWatcherService
    directory.mkdir(parents=True)
    result = []
    for mode in ('unrelated', 'includes', 'full', 'exact', 'failure', 'queued'):
        owner = directory/mode
        owner.mkdir()
        ctx = Context()
        ctx.baseUrl = owner.as_uri()+'/'
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, dict(root=[], debounce=10))
        hmr, loader = ctx.get('hmr'), ctx.loader
        trace, release = [], asyncio.Event()
        ctx.on('hmr/change', lambda url: trace.append('change:'+Path(url).name))
        original_wait = loader.await_
        async def wait():
            trace.append('await')
            await original_wait()
        loader.await_ = wait
        loader.exit = lambda: trace.append('exit')
        partial_count = [0]
        async def partial():
            partial_count[0] += 1
            trace.append('partial:'+','.join(sorted(Path(url).name for url in hmr._stashed)))
            if mode == 'failure' and partial_count[0] == 1:
                raise RuntimeError('replacement failed')
        hmr.partialReload = partial
        invalidated = []
        hmr.invalidate_manifest = lambda filename: invalidated.append(Path(filename).name)
        def emit(*files):
            for filename in files:
                hmr._module_changed(filename)
        async def drain():
            await asyncio.sleep(.05)
            await hmr.runExclusive(lambda: None)
        try:
            if mode == 'unrelated':
                emit('package.json.lock', 'package.json', 'note.txt', 'note.txt')
                await drain()
            elif mode in ('includes', 'full', 'queued'):
                for name in ('first.yml', 'second.yml'):
                    (owner/name).write_text('[]', encoding='utf-8')
                    entry_id = await loader.create(dict(name='cordis:include', config=dict(path=(owner/name).as_uri())))
                    await original_wait()
                    include = loader.resolve(entry_id).subtree
                    refresh = include.refresh
                    async def wrapped(name=name, refresh=refresh):
                        trace.append('refresh:'+name)
                        if mode == 'includes' and name == 'first.yml':
                            raise RuntimeError('unsaved runtime change')
                        await refresh()
                    include.refresh = wrapped
                loader.internal.loadCache[(owner/'cached.js').as_uri()] = None
                if mode == 'full':
                    hmr.externals.add((owner/'framework.js').as_uri())
                    emit('first.yml', 'cached.js', 'framework.js', 'note.txt')
                elif mode == 'queued':
                    entered = asyncio.Event()
                    async def mutation():
                        entered.set()
                        await release.wait()
                        trace.append('write')
                    job = hmr.runExclusive(mutation)
                    await entered.wait()
                    emit('first.yml', 'cached.js', 'first.yml', 'second.yml')
                    await asyncio.sleep(.05)
                    before = list(trace)
                    release.set()
                    await job
                else:
                    emit('first.yml', 'first.yml', 'second.yml')
                await drain()
            elif mode == 'exact':
                dispose = await hmr.watchConfig(str(owner/'missing.yml'), lambda: trace.append('exact'))
                emit('missing.yml', 'note.txt')
                await drain()
                await dispose()
            else:
                loader.internal.loadCache[(owner/'cached.js').as_uri()] = None
                emit('cached.js')
                await drain()
                emit('cached.js')
                await drain()
            result.append(dict(case=mode, trace=trace, invalidated=invalidated, stashed=len(hmr._stashed),
                               **(dict(before=before) if mode == 'queued' else {})))
        finally:
            release.set()
            await ctx.fiber.dispose()
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 20)


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'reference'
    probe.main('rc022_hmr_dispatch.mts', 'Actual service root-event batch classification, exact path suppression, Include failure containment, full reload precedence, queue ordering and replacement failure recovery.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/cordis/hmr_dispatch.py', source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
