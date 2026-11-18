"""Exercise actual source files through canonical root module replacement."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ['unchanged', 'upgrade', 'syntax', 'activation', 'shared', 'helper', 'removed', 'disabled', 'config', 'unmanaged']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(MODES), encoding='utf-8')
    return [path]


async def observe(directory, modes=MODES):
    from dsh.cordis.context import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.hmr_modules import module_url
    directory.mkdir(parents=True)
    result = []
    for mode in modes:
        owner = directory/mode
        owner.mkdir()
        source, helper = owner/'plugin.py', owner/('_rc022_partial_helper_'+mode+'.py')
        helper.write_text('value = 1\n', encoding='utf-8')
        def write(value, failed=False):
            source.write_text(('from '+helper.stem+' import value\n' if mode == 'helper' else 'value = '+str(value)+'\n')
                +'def apply(ctx, config):\n'
                +'    ctx.get("reloadTrace").append("start:"+str(value)+":"+config["label"])\n'
                +('    raise RuntimeError("activation failed")\n' if failed else
                  '    ctx.effect(lambda: lambda: ctx.get("reloadTrace").append("stop:"+str(value)+":"+config["label"]))\n'), encoding='utf-8')
        write(1)
        ctx, trace = Context(), []
        ctx.baseUrl = owner.as_uri()+'/'
        ctx.provide('reloadTrace', trace)
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, dict(root=[]))
        hmr, loader = ctx.get('hmr'), ctx.loader
        sys.path.insert(0, str(owner))
        try:
            if mode == 'disabled':
                loader.import_plugin(str(source))
            entry_id = await loader.create(dict(name=str(source), config=dict(label='initial'), disabled=mode == 'disabled'))
            await loader.await_()
            entry = loader.resolve(entry_id)
            before, namespace = entry.fiber, getattr(entry, 'moduleNamespace', None)
            if mode == 'shared':
                await loader.create(dict(name=str(source), config=dict(label='other')))
                await loader.await_()
            if mode == 'unmanaged':
                await ctx.plugin(loader.import_plugin(str(source)), dict(label='unmanaged'))
            if mode == 'removed':
                await ctx.registry.delete_async(loader.unwrap_exports(namespace))
            if mode == 'config':
                entry.options['config'] = dict(label='latest')
            trace.clear()
            reloaded = []
            ctx.on('hmr/reload', lambda rows: reloaded.append(len(rows)))
            if mode != 'unchanged':
                write(2, mode == 'activation')
                if mode == 'syntax':
                    source.write_text('invalid = (\n', encoding='utf-8')
                if mode == 'helper':
                    helper.write_text('value = 2\n', encoding='utf-8')
                hmr._stashed[(helper if mode == 'helper' else source).as_uri()] = None
            failed = False
            try:
                await hmr.runExclusive(lambda: hmr.partialReload())
            except Exception:
                failed = True
            result.append(dict(mode=mode, failed=failed, trace=list(trace), same=entry.fiber is before,
                namespace_same=getattr(entry, 'moduleNamespace', None) is namespace,
                cached_old=loader.internal.loadCache.get(source.as_uri()) is namespace,
                active=entry.fiber is not None and entry.fiber.uid is not None, reloaded=list(reloaded)))
            if mode in ('syntax', 'activation'):
                trace.clear()
                write(3)
                await hmr.runExclusive(lambda: hmr.partialReload())
                result.append(dict(mode=mode+'-recovered', trace=list(trace), namespace_same=entry.moduleNamespace is namespace, reloaded=list(reloaded)))
        finally:
            await ctx.fiber.dispose()
            sys.path.remove(str(owner))
            for name, module in list(sys.modules.items()):
                url = module_url(module)
                if url is not None and url.startswith(owner.as_uri()+'/'):
                    sys.modules.pop(name, None)
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 25)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_hmr_partial.mts', 'Actual file module partialReload: unchanged, source/helper upgrade, latest entry configuration, shared/unmanaged instances, disabled/removed runtime, syntax and activation failure then correction.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_partial.py', ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/cordis/hmr_changes.py', ROOT/'dsh/cordis/hmr_modules.py', ROOT/'reference/packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
