"""Pair application readiness, shutdown and initial profile module observations."""
import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output / 'input.json'
    path.write_text('{}', encoding='utf-8')
    return [path]


async def observe(directory):
    from dsh.cordis.context import Context
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    from dsh.boot.profile_boot import create_app_ready
    directory.mkdir(parents=True)
    result = []
    async def fixture(name, ready=True):
        owner = directory / name
        profile = owner / 'profile'
        profile.mkdir(parents=True)
        ctx = Context()
        ctx.baseUrl = profile.as_uri()+'/'
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        ctx.provide('profileContext', dict(dir=str(profile), home=str(owner), patchPath=str(profile/'patch.json'), startedBundles=[]))
        signal = create_app_ready()
        if ready:
            ctx.provide('appReady', signal['service'])
        return ctx, signal, profile

    ctx, signal, profile = await fixture('missing', False)
    try:
        try:
            await ctx.plugin(ConfigWatcherService, dict(root=[]))
        except Exception as error:
            result.append(dict(case='requires-ready', rejected='Profile HMR requires application readiness' in str(error)))
    finally:
        await ctx.fiber.dispose()

    for mode in ('commit', 'cancel', 'baseline-error'):
        ctx, signal, profile = await fixture(mode)
        await ctx.plugin(ConfigWatcherService, dict(root=[]))
        hmr = ctx.get('hmr')
        filename = profile/'watched.json'
        filename.write_text('{}', encoding='utf-8')
        called, completed = [], asyncio.Event()
        async def refresh():
            called.append('refresh')
            completed.set()
        try:
            # Caller mutations do not await successful startup.
            value = await hmr.runExclusive(lambda: 42)
            dispose = await hmr.watchConfig(str(filename), refresh)
            await asyncio.sleep(0)
            before = list(called)
            if mode == 'cancel':
                await ctx.fiber.dispose()
                signal['commit']()
            else:
                if mode == 'baseline-error':
                    def broken(*args): raise RuntimeError('observation failed')
                    hmr.files.observe = broken
                signal['commit']()
                await completed.wait()
                await dispose()
            result.append(dict(case=mode, mutation=value, before=before, after=called))
        finally:
            await ctx.fiber.dispose()

    ctx, signal, profile = await fixture('baseline')
    outside = profile.parent/'linked'
    outside.mkdir()
    modules = profile/'node_modules/@scope'
    modules.mkdir(parents=True)
    link = modules/'linked'
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    ordinary = modules/'ordinary'
    ordinary.mkdir()
    paths = [profile/'local.py', outside/'linked.py', profile.parent/'sibling.py', ordinary/'nested.py']
    for path in paths:
        path.write_text('pass\n', encoding='utf-8')
    try:
        for path in paths:
            ctx.loader.internal.loadCache[path.as_uri()] = None
        await ctx.plugin(ConfigWatcherService, dict(root=[]))
        signal['commit']()
        stale = ctx.get('hmr').files.compare([path.as_uri() for path in paths])['stale']
        result.append(dict(case='initial-profile-and-linked-records', stale=[path.name for path in paths if path.as_uri() in stale]))
    finally:
        await ctx.fiber.dispose()
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT/'files/native'), 10)


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_hmr_ready.mts', 'Application startup barrier for queued reloads, cancellation, and production initial module identity capture including linked packages. Profile automatic watches and reconciliation are separate.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/cordis/hmr_paths.py', ROOT/'dsh/cordis/hmr_files.py',
                source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
