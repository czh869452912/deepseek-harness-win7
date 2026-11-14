"""Observe actual profile/home/manifest file edits through HMR's own watchers."""
import asyncio
import json
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


async def observe(directory, settle_before_exit=True):
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.profile_boot import create_app_ready
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    directory.mkdir(parents=True)
    result = []
    for mode in ('commit', 'cancel'):
        owner = directory/mode
        profile = owner/'profile'
        profile.mkdir(parents=True)
        root = profile/'cordis.yml'
        root.write_text('[]', encoding='utf-8')
        manifest, patch, home_patch = profile/'package.json', profile/'cordis.patch.yml', owner/'cordis.patch.yml'
        manifest_value = dict(name='test', dsh=dict(profile=dict(bundles=[])))
        manifest.write_text(json.dumps(manifest_value), encoding='utf-8')
        rows = [dict(insert=[dict(id='timer', name='cordis:timer'), dict(id='hmr', name='cordis:hmr', config=dict(root=[])),
                             dict(id='probe', name='cordis:probe', config=dict(value='initial'))])]
        patch.write_text(json.dumps(rows), encoding='utf-8')
        context = dict(dir=str(profile), home=str(owner), patchPath=str(patch), startedBundles=[], installAnchor=str(owner/'package.json'), overlays=[], telemetryDisabledEnv=None)
        signal = create_app_ready()
        events = []
        def setup(ctx):
            ctx.provide('profileContext', context)
            ctx.provide('appReady', signal['service'])
            ctx.loader.builtins['timer'] = TimerService
            ctx.loader.builtins['hmr'] = ConfigWatcherService
            ctx.loader.builtins['probe'] = lambda owner, config: owner.provide('probeValue', config['value'])
            ctx.on('app-boot/config-reload', lambda: events.append('reload'))
        ctx = await boot('test', str(root), read_profile_patches('test', context), setup)
        hmr = ctx.get('hmr')
        async def until(condition):
            for unused in range(1000):
                if condition():
                    return
                await asyncio.sleep(.01)
            raise RuntimeError('profile watcher did not converge')
        try:
            rows[0]['insert'][-1]['config']['value'] = 'edited-before-ready'
            patch.write_text(json.dumps(rows), encoding='utf-8')
            before = ctx.get('probeValue')
            if mode == 'cancel':
                await asyncio.wait_for(ctx.fiber.dispose(), 3)
                signal['commit']()
                result.append(dict(mode=mode, before=before, value=ctx.get('probeValue'), active=ctx.get('hmr') is not None))
                continue
            signal['commit']()
            await until(lambda: ctx.get('probeValue') == 'edited-before-ready')
            await hmr.runExclusive(lambda: None)
            result.append(dict(step='ready', before=before, value=ctx.get('probeValue')))
            home_patch.write_text(json.dumps([dict(id='probe', config=dict(value='home'))]), encoding='utf-8')
            await until(lambda: ctx.get('probeValue') == 'home')
            await hmr.runExclusive(lambda: None)
            result.append(dict(step='home', value=ctx.get('probeValue')))
            await asyncio.sleep(.15)
            home_patch.unlink()
            await until(lambda: ctx.get('probeValue') == 'edited-before-ready')
            await hmr.runExclusive(lambda: None)
            result.append(dict(step='home-unlink', value=ctx.get('probeValue')))
            count = len(events)
            manifest_value['dependencies'] = dict(unselected='1.0.0')
            manifest.write_text(json.dumps(manifest_value), encoding='utf-8')
            await asyncio.sleep(.2)
            await hmr.runExclusive(lambda: None)
            result.append(dict(step='dependencies-only', reloaded=len(events) != count))
            bundle = profile/'node_modules/added'
            bundle.mkdir(parents=True)
            (bundle/'package.json').write_text(json.dumps(dict(name='added', dsh=dict(bundle=dict(patch='./patch.json')))), encoding='utf-8')
            (bundle/'patch.json').write_text(json.dumps([dict(insert=[dict(id='bundled', name='cordis:probe', disabled=True)])]), encoding='utf-8')
            manifest_value['dsh']['profile']['bundles'] = ['added']
            manifest.write_text(json.dumps(manifest_value), encoding='utf-8')
            await until(lambda: any(entry.options['id'] == 'bundled' for entry in ctx.loader.entries()))
            await hmr.runExclusive(lambda: None)
            count = len(events)
            result.append(dict(step='bundles', bundled=True, value=ctx.get('probeValue')))
            # A new notification with unchanged inputs must not recompose again.
            patch.write_text(json.dumps(rows)+'\n', encoding='utf-8')
            await until(lambda: len(events) > count)
            await hmr.runExclusive(lambda: None)
            count = len(events)
            patch.write_text(json.dumps(rows)+'\n', encoding='utf-8')
            await asyncio.sleep(.2)
            await hmr.runExclusive(lambda: None)
            result.append(dict(step='unchanged-inputs', reloaded=len(events) != count))
            rows[0]['insert'][1]['config'] = dict(root=[], debounce=1)
            patch.write_text(json.dumps(rows), encoding='utf-8')
            await until(lambda: ctx.get('hmr') is not None and ctx.get('hmr')._executing is not hmr._executing)
            rows[0]['insert'][-1]['config']['value'] = 'after-hmr-replacement'
            patch.write_text(json.dumps(rows), encoding='utf-8')
            await until(lambda: ctx.get('probeValue') == 'after-hmr-replacement')
            if settle_before_exit:
                await ctx.get('hmr').runExclusive(lambda: None)
            result.append(dict(step='provider-replacement', old_active=hmr._running, value=ctx.get('probeValue')))
        finally:
            await ctx.fiber.dispose()
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 35)


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_hmr_watch.mts', 'Real filesystem profile/home/manifest changes, readiness, unlink, dependency-only suppression, bundle selection, repeated input deduplication and HMR self-replacement.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/cordis/hmr_profile_watch.py', ROOT/'dsh/boot/profile_boot.py',
                source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
