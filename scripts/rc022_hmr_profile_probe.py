"""Pair actual profile code replacement through the production HMR service."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
MODES = ['unchanged', 'upgrade', 'failure', 'syntax', 'remove', 'unmanaged', 'host', 'shared', 'comparison-failure']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(MODES), encoding='utf-8')
    return [path]


async def observe(directory, modes=MODES):
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_boot import create_app_ready
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    from dsh.cordis.hmr_modules import module_url
    directory.mkdir(parents=True)
    result = []
    for mode in modes:
        owner = directory/mode
        profile = owner/'profile'
        profile.mkdir(parents=True)
        (profile/'package.json').write_text(json.dumps(dict(name='test', dsh=dict(profile=dict(bundles=[])))), encoding='utf-8')
        root = profile/'cordis.yml'
        root.write_text('[]', encoding='utf-8')
        entry = profile/'plugin.py'
        helper = profile/('_rc022_profile_helper_'+mode.replace('-', '_')+'.py')
        helper.write_text('value = 1\n', encoding='utf-8')
        def write(value, failed=False):
            prefix = 'from %s import value\n'%helper.stem if mode == 'shared' else 'value = %d\n'%value
            entry.write_text(prefix+'def apply(ctx, config):\n'
                +'    ctx.get("reloadTrace").append("start:"+str(value))\n'
                + ('    raise RuntimeError("activation failed")\n' if failed else
                   '    if ctx.get("probeValue") is None: ctx.provide("probeValue", value)\n    ctx.effect(lambda: lambda: ctx.get("reloadTrace").append("stop:"+str(value)))\n'), encoding='utf-8')
        write(1)
        rows = [dict(id='probe', name='./plugin.py')]
        patches = [dict(insert=rows)]
        signal, trace = create_app_ready(), []
        context = dict(dir=str(profile), home=str(owner), patchPath=str(profile/'patch.json'), startedBundles=[],
                       installAnchor=str(owner/'package.json'), overlays=patches, telemetryDisabledEnv=None)
        def setup(ctx):
            ctx.provide('profileContext', context)
            ctx.provide('appReady', signal['service'])
            ctx.provide('reloadTrace', trace)
        sys.path.insert(0, str(profile))
        ctx = await boot('test', str(root), patches, setup)
        try:
            await ctx.plugin(TimerService)
            await ctx.plugin(ConfigWatcherService, dict(root=[]))
            hmr = ctx.get('hmr')
            signal['commit']()
            initial = next(row for row in ctx.loader.entries() if row.options['id'] == 'probe')
            before = initial.fiber
            trace.clear()
            if mode == 'unmanaged':
                imported = ctx.loader.import_plugin(str(entry))
                await ctx.plugin(imported)
                trace.clear()
            if mode == 'host':
                hmr.modules._host = {entry.as_uri()}
            if mode == 'comparison-failure':
                def broken(*args): raise OSError('comparison failed')
                hmr.files.compare = broken
            if mode != 'unchanged':
                write(2, mode == 'failure')
                if mode == 'syntax':
                    entry.write_text('invalid = (\n', encoding='utf-8')
                elif mode == 'shared':
                    helper.write_text('value = 2\n', encoding='utf-8')
                elif mode == 'remove':
                    context['overlays'] = []
            failed = False
            try:
                outcome = await hmr.runExclusive(lambda: hmr.reconcileProfile())
            except Exception:
                failed, outcome = True, None
            current = next((row for row in ctx.loader.entries() if row.options['id'] == 'probe'), None)
            result.append(dict(mode=mode, failed=failed, value=ctx.get('probeValue'), trace=list(trace),
                               same=current is not None and current.fiber is before,
                               pending=None if outcome is None else [dict(file=Path(item['url']).name, reason=item['reason']) for item in outcome['pending']],
                               restart=None if outcome is None else outcome.get('restartReason')))
            if mode in ('failure', 'syntax', 'remove'):
                trace.clear()
                write(3)
                context['overlays'] = patches
                recovered = await hmr.runExclusive(lambda: hmr.reconcileProfile())
                result.append(dict(mode=mode+'-recovered', value=ctx.get('probeValue'), trace=list(trace), pending=recovered['pending']))
        finally:
            await ctx.fiber.dispose()
            sys.path.remove(str(profile))
            for name, module in list(sys.modules.items()):
                url = module_url(module)
                if url is not None and url.startswith(profile.as_uri()+'/'):
                    sys.modules.pop(name, None)
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 25)


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'reference'
    probe.main('rc022_hmr_profile.mts', 'Actual profile module replacement, no-change retention, failure, removal, host/unmanaged exclusions, shared helper and contained comparison failure. No automatic watcher dispatch claim.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_profile.py', ROOT/'dsh/cordis/hmr_modules.py', ROOT/'dsh/cordis/hmr_plan.py',
                ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/boot/recomposition.py', source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
