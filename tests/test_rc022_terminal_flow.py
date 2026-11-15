import asyncio

import pytest

from dsh.api.terminal_retention_authorized import TerminalRetention
from dsh.api.terminal_stream_authorized import TerminalFollower
from dsh.core.abort import AbortController
from scripts.rc022_terminal_flow_probe import Clock


POLICY=dict(unattendedTimeoutMs=100,activityPollIntervalMs=10,cleanupRetryMs=20)


@pytest.mark.asyncio
async def test_retention_deadlines_holds_busy_unknown_revisions_and_large_retry():
    from scripts.rc022_terminal_flow_probe import observe
    rows={row['name']:row for row in await observe()}
    for name,deadline in [('idle',100),('holds',600),('busy',1110),('unknown',1110),('revision',200)]:
        assert rows[name+'-before']['calls'] == []
        assert rows[name+'-after']['calls'] == [deadline]
    assert rows['retry-after']['calls'] == [100,120]
    assert rows['closed-on-failure']['code'] == 'terminal/unavailable'
    assert rows['huge-retry-before']['calls'] == [0]
    assert rows['huge-retry-after']['calls'] == [0,3000000000]
    assert all(row['timers'] == 0 for key,row in rows.items() if key.endswith('-disposed'))


@pytest.mark.asyncio
async def test_reconnect_invalidates_inflight_observation_without_overlapping_queries():
    clock=Clock();observed=asyncio.get_running_loop().create_future();queries=[];terminated=[]
    async def inspect():
        queries.append(clock.now())
        return await observed if len(queries)==1 else dict(state='idle',revision=1)
    async def terminate():terminated.append(clock.now())
    owner=TerminalRetention(POLICY,inspect,terminate,lambda error:pytest.fail(str(error)),clock)
    controller=AbortController();stream=None
    try:
        await clock.advance(0)
        stream=owner.retain(controller.signal);assert await stream.__anext__() == dict(type='retained')
        controller.abort();await clock.advance(0);assert queries == [0]
        observed.set_result(dict(state='idle',revision=1));await clock.pump()
        await clock.advance(109);assert terminated == []
        await clock.advance(1);assert terminated == [110]
    finally:
        if not observed.done():observed.set_result(dict(state='unknown',revision=1))
        await owner.dispose()
        if stream is not None:await stream.aclose()


@pytest.mark.asyncio
async def test_dispose_waits_for_observation_even_when_cleanup_fails():
    clock=Clock();observed=asyncio.get_running_loop().create_future();failure=RuntimeError('cleanup failed')
    async def inspect():return await observed
    async def terminate():raise failure
    owner=TerminalRetention(POLICY,inspect,terminate,lambda error:pytest.fail(str(error)),clock)
    await clock.advance(0);disposed=asyncio.ensure_future(owner.dispose());await clock.pump()
    assert not disposed.done()
    observed.set_result(dict(state='unknown',revision=1))
    with pytest.raises(RuntimeError) as caught:await disposed
    assert caught.value is failure and clock.count()==0
    # Failure leaves the identity closed; owner may explicitly retry cleanup.
    async def succeeds():pass
    owner.terminate=succeeds;await owner.dispose()


@pytest.mark.asyncio
async def test_cleanup_is_joined_and_awaiter_cancellation_does_not_cancel_process_cleanup():
    clock=Clock();release=asyncio.get_running_loop().create_future();calls=[]
    async def inspect():return dict(state='unknown',revision=1)
    async def terminate():calls.append(True);await release
    owner=TerminalRetention(dict(POLICY,unattendedTimeoutMs=0),inspect,terminate,lambda error:pytest.fail(str(error)),clock)
    first=owner.close();assert owner.close() is first
    async def wait():await first
    abandoned=asyncio.ensure_future(wait());await clock.pump();abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):await abandoned
    assert not release.cancelled() and calls == [True]
    release.set_result(None);await owner.dispose();assert calls == [True] and clock.count()==0


@pytest.mark.asyncio
async def test_observation_gap_and_failure_restart_full_grace():
    clock=Clock();failed=[False];terminated=[]
    async def inspect():
        if failed[0]:failed[0]=False;raise OSError('activity unavailable')
        return dict(state='idle',revision=1)
    async def terminate():terminated.append(clock.now())
    owner=TerminalRetention(POLICY,inspect,terminate,lambda error:pytest.fail(str(error)),clock)
    try:
        await clock.advance(90);failed[0]=True;await clock.advance(110);assert not terminated
        await clock.advance(10);assert terminated == [210]
    finally:await owner.dispose()


@pytest.mark.asyncio
async def test_follower_consumer_return_closes_and_late_failure_cannot_replace_finish():
    frame=dict(type='output',sequence=1,data='text');follower=TerminalFollower(1000)
    follower.push(frame);stream=follower.read(AbortController().signal)
    assert await stream.__anext__() is frame
    await stream.aclose();follower.fail(RuntimeError('late failure'));follower.push(frame)
    assert [item async for item in follower.read(AbortController().signal)] == []
    follower=TerminalFollower(1000);follower.push(frame);follower.finish();follower.fail(RuntimeError('late input'))
    assert [item async for item in follower.read(AbortController().signal)] == [frame]
