"""Observe HMR queue ownership against the fixed, unchanged upstream service."""
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
    return [output]


async def observe(directory):
    from dsh.cordis.context import Context
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService

    directory.mkdir(parents=True)
    result = []

    async def fixture(name):
        owner = directory / name
        owner.mkdir()
        ctx = Context()
        ctx.baseUrl = owner.as_uri() + '/'
        await ctx.plugin(Loader)
        await ctx.plugin(TimerService)
        await ctx.plugin(ConfigWatcherService, {'root': [], 'debounce': 0})
        return ctx, ctx.get('hmr'), owner

    ctx, hmr, owner = await fixture('serial')
    release, entered = asyncio.Event(), asyncio.Event()
    order = []
    async def first():
        order.append('first')
        entered.set()
        await release.wait()
        raise ValueError('mutation failed')
    async def second():
        order.append('second')
        try:
            await hmr.runExclusive(lambda: None)
        except RuntimeError as error:
            order.append(str(error))
        return 42
    try:
        failure = hmr.runExclusive(first)
        await entered.wait()
        next_job = hmr.runExclusive(second)
        before = list(order)
        release.set()
        try:
            await failure
        except ValueError as error:
            reason = str(error)
        value = await next_job
        result.append(dict(case='failure-and-nesting', before=before, order=order, reason=reason, value=value))
    finally:
        release.set()
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('watch')
    release, entered, refreshed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    order = []
    async def mutation():
        entered.set()
        await release.wait()
        order.append('write')
    async def refresh():
        order.append('refresh')
        refreshed.set()
    try:
        job = hmr.runExclusive(mutation)
        await entered.wait()
        filename = owner / 'config.json'
        filename.write_text('{}', encoding='utf-8')
        dispose = await hmr.watchConfig(str(filename), refresh)
        try:
            await hmr.watchConfig(str(filename), refresh)
        except ValueError:
            duplicate = True
        await asyncio.sleep(0)
        before = list(order)
        release.set()
        await job
        await refreshed.wait()
        await dispose()
        again = await hmr.watchConfig(str(owner / 'missing.json'), refresh)
        await hmr.runExclusive(lambda: again())
        result.append(dict(case='watch-queue-and-dispose', before=before, order=order, duplicate=duplicate))
    finally:
        release.set()
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('register-in-transaction')
    order, refreshed = [], asyncio.Event()
    filename = owner / 'config.json'
    filename.write_text('{}', encoding='utf-8')
    async def refresh_inside():
        order.append('refresh')
        refreshed.set()
    async def register():
        dispose = await hmr.watchConfig(str(filename), refresh_inside)
        order.append('registered')
        return dispose
    try:
        dispose = await hmr.runExclusive(register)
        await refreshed.wait()
        await dispose()
        result.append(dict(case='watch-exits-transaction-context', order=order))
    finally:
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('drain-watch')
    release, entered = asyncio.Event(), asyncio.Event()
    filename = owner / 'config.json'
    filename.write_text('{}', encoding='utf-8')
    order = []
    async def held():
        entered.set()
        await release.wait()
        order.append('refresh-completed')
    try:
        dispose = await hmr.watchConfig(str(filename), held)
        await entered.wait()
        async def close():
            await dispose()
            order.append('disposed')
        closing = asyncio.create_task(close())
        await asyncio.sleep(0)
        before = list(order)
        release.set()
        await closing
        result.append(dict(case='external-watch-drains', before=before, order=order))
    finally:
        release.set()
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('self-dispose')
    try:
        await hmr.runExclusive(lambda: ctx.fiber.dispose())
        try:
            await hmr.runExclusive(lambda: None)
        except RuntimeError as error:
            result.append(dict(case='self-dispose', reason=str(error)))
    finally:
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('drain-owner')
    release, entered = asyncio.Event(), asyncio.Event()
    order = []
    async def held_mutation():
        entered.set()
        await release.wait()
        order.append('mutation-completed')
    try:
        job = hmr.runExclusive(held_mutation)
        await entered.wait()
        async def close_owner():
            await ctx.fiber.dispose()
            order.append('disposed')
        closing = asyncio.create_task(close_owner())
        await asyncio.sleep(0)
        before = list(order)
        release.set()
        await job
        await closing
        result.append(dict(case='external-owner-drains', before=before, order=order))
    finally:
        release.set()
        await ctx.fiber.dispose()

    ctx, hmr, owner = await fixture('start-failure')
    filename = owner / 'parent/config.json'
    filename.parent.write_text('file', encoding='utf-8')
    try:
        failed = False
        try:
            await hmr.watchConfig(str(filename), lambda: None)
        except (OSError, RuntimeError):
            failed = True
        filename.parent.unlink()
        filename.parent.mkdir()
        dispose = await hmr.watchConfig(str(filename), lambda: None)
        await dispose()
        result.append(dict(case='failed-start-releases-path', failed=failed, retry=True))
    finally:
        await ctx.fiber.dispose()
    return result


async def native():
    return await asyncio.wait_for(observe(OUTPUT / 'files/native'), 15)


if __name__ == '__main__':
    probe.native = native
    source = ROOT / '.goose/out/rc022-prep-20261114-01/source'
    # prepare returns the output directory, not a hashed fixture input.
    def paired_prepare(output):
        prepare(output)
        marker = output / 'input.json'
        marker.write_text('{}', encoding='utf-8')
        return [marker]
    probe.main('rc022_hmr_queue.mts', 'Actual service-owned serial queue and exact-file watcher disposal; no module replacement or profile readiness claim.',
               [Path(__file__).resolve(), ROOT / 'dsh/cordis/hmr.py', source / 'packages/boot/hmr/src/index.ts',
                source / 'packages/boot/hmr/src/watch-config.ts'], paired_prepare, node_args=('--expose-internals',))
