import asyncio
import os
from pathlib import Path

import pytest

from scripts.rc022_hmr_dispatch_probe import observe


@pytest.mark.asyncio
async def test_root_batches_share_the_mutation_queue_and_classify_once(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'root-events'), 20)
    assert rows == [
        dict(case='unrelated', trace=['change:package.json.lock', 'change:note.txt'], invalidated=['package.json'], stashed=0),
        dict(case='includes', trace=['refresh:first.yml', 'refresh:second.yml', 'await'], invalidated=[], stashed=0),
        dict(case='full', trace=['change:note.txt', 'exit'], invalidated=[], stashed=1),
        dict(case='exact', trace=['change:note.txt'], invalidated=[], stashed=0),
        dict(case='failure', trace=['partial:cached.js', 'partial:cached.js', 'await'], invalidated=[], stashed=0),
        dict(case='queued', trace=['write', 'refresh:first.yml', 'refresh:second.yml', 'partial:cached.js', 'await'], invalidated=[], stashed=0, before=[]),
    ]


@pytest.mark.asyncio
async def test_portable_poller_queues_real_root_changes_behind_mutations(tmp_path):
    from dsh.cordis.context import Context
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    ctx = Context()
    ctx.baseUrl = tmp_path.as_uri()+'/'
    filename = tmp_path/'note.txt'
    filename.write_text('before', encoding='utf-8')
    await ctx.plugin(Loader)
    await ctx.plugin(TimerService)
    await ctx.plugin(ConfigWatcherService, dict(root=['.'], debounce=10))
    hmr = ctx.get('hmr')
    events, release, entered = [], asyncio.Event(), asyncio.Event()
    ctx.on('hmr/change', lambda url: events.append(Path(url).name))
    async def until(condition):
        for unused in range(200):
            if condition():
                return
            await asyncio.sleep(.01)
        raise AssertionError('poller did not converge')
    async def mutation():
        entered.set()
        await release.wait()
        events.append('write')
    try:
        await until(lambda: hmr._initial_scanned)
        job = hmr.runExclusive(mutation)
        await entered.wait()
        # A timestamp moving backwards must still count as a change.
        stamp = filename.stat().st_mtime
        filename.write_text('after!', encoding='utf-8')
        os.utime(str(filename), (stamp-10, stamp-10))
        await until(lambda: hmr._root_mtimes[str(filename)][0] == stamp-10)
        await asyncio.sleep(.03)
        assert events == []
        release.set()
        await job
        await until(lambda: events == ['write', 'note.txt'])
        await hmr.runExclusive(lambda: None)
    finally:
        release.set()
        await ctx.fiber.dispose()
