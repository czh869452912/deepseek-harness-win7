import asyncio

import pytest

from dsh.core.cleanup import CleanupPromise, SharedPromise
from scripts.rc022_workflow_result_probe import observe


@pytest.mark.asyncio
async def test_result_observer_cancellation_and_timeout_keep_owner_alive():
    rows = await observe()
    for row in rows:
        assert row['pending'] and row['sameHandle'] and row['sameValue']
        assert row['stillActive'] == (row['kind'] != 'teardown')
        assert row['callbacks'] == [True]
        assert row['pendingJobs'] == row['children'] == 0 and row['detached']
    assert rows[3]['heldChildren'] == 1 and rows[3]['disposed'] == ['child']
    assert rows[4]['result']['error'] == 'runtime rejected'
    assert rows[5]['result']['stopReason'] == 'cancelled'
    assert rows[5]['result']['error'].endswith('holder stopped')


@pytest.mark.asyncio
@pytest.mark.parametrize('promise_type', [SharedPromise, CleanupPromise])
async def test_owner_failure_is_retained_after_observer_leaves(promise_type):
    entered, release = asyncio.Event(), asyncio.Event()
    failure = ValueError('retained failure')
    async def operation():
        entered.set(); await release.wait(); raise failure
    shared = promise_type(operation())
    callbacks = []
    shared.add_done_callback(callbacks.append)
    async def wait(): return await shared
    waiter = asyncio.create_task(wait())
    await entered.wait(); await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError): await waiter
    assert not shared.done() and not shared.cancelled()
    release.set()
    with pytest.raises(ValueError) as caught: await shared
    assert caught.value is failure
    await asyncio.sleep(0)
    assert shared.done() and shared.exception() is failure and callbacks == [shared]
    with pytest.raises(ValueError) as caught: shared.result()
    assert caught.value is failure
