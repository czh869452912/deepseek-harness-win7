import asyncio
import errno

import pytest

from scripts.rc022_hmr_queue_probe import observe


@pytest.mark.asyncio
async def test_hmr_queue_actual_owner_and_exact_file_disposal(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path / 'observations'), 10)
    assert rows == [
        dict(case='failure-and-nesting', before=['first'],
             order=['first', 'second', 'HMR transactions cannot be nested'], reason='mutation failed', value=42),
        dict(case='watch-queue-and-dispose', before=[], order=['write', 'refresh'], duplicate=True),
        dict(case='watch-exits-transaction-context', order=['registered', 'refresh']),
        dict(case='external-watch-drains', before=[], order=['refresh-completed', 'disposed']),
        dict(case='self-dispose', reason='HMR is disposed'),
        dict(case='external-owner-drains', before=[], order=['mutation-completed', 'disposed']),
        dict(case='failed-start-releases-path', failed=True, retry=True),
    ]


def test_exact_watch_parent_permission_failure_is_not_missing(monkeypatch, tmp_path):
    from dsh.cordis import hmr
    def denied(path):
        raise OSError(errno.EACCES, 'denied', str(path))
    monkeypatch.setattr(hmr.os, 'stat', denied)
    with pytest.raises(OSError) as caught:
        hmr.find_watch_root(str(tmp_path / 'config.json'))
    assert caught.value.errno == errno.EACCES


@pytest.mark.asyncio
async def test_cancelling_caller_wait_does_not_cancel_owned_queue():
    from dsh.cordis.context import Context
    from dsh.cordis.hmr import ConfigWatcherService
    ctx = Context()
    hmr = ConfigWatcherService(ctx, {'root': []})
    release, entered = asyncio.Event(), asyncio.Event()
    order = []
    async def mutation():
        entered.set()
        await release.wait()
        order.append('owned')
    try:
        waiting = hmr.runExclusive(mutation)
        await entered.wait()
        waiting.cancel()
        following = hmr.runExclusive(lambda: order.append('following'))
        await asyncio.sleep(0)
        assert order == []
        release.set()
        await asyncio.wait_for(following, 2)
        assert order == ['owned', 'following']
    finally:
        release.set()
        await hmr.teardown()
        await ctx.fiber.dispose()
