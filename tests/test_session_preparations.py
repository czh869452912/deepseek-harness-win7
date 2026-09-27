import asyncio
from types import SimpleNamespace
import pytest
from dsh.core.abort import AbortController
from dsh.session.preparations import SessionPreparations, observe_queued_abort

def source(sid):
    return SimpleNamespace(session=SimpleNamespace(id=sid))
async def commit(value):
    return {'source':value,'state':{}}
async def settle():
    for _ in range(8): await asyncio.sleep(0)

@pytest.mark.asyncio
async def test_shared_load_survives_first_signal_cancellation():
    pool=SessionPreparations(2);gate=asyncio.get_running_loop().create_future();calls=[]
    def load():calls.append(1);return gate
    abort=AbortController();error=ValueError('cancel observer')
    first=asyncio.create_task(pool.inspect('s',load,abort.signal))
    second=asyncio.create_task(pool.inspect('s',load))
    await settle();abort.abort(error)
    with pytest.raises(ValueError) as caught:await first
    assert caught.value is error and not gate.cancelled()
    value=source('s');gate.set_result(value)
    assert await second is value
    assert await pool.inspect('s',load) is value and len(calls)==1

@pytest.mark.asyncio
async def test_python_observer_cancellation_never_cancels_shared_loader():
    pool=SessionPreparations();gate=asyncio.get_running_loop().create_future()
    job=asyncio.create_task(pool.inspect('s',lambda:gate));await settle();job.cancel()
    with pytest.raises(asyncio.CancelledError):await job
    assert not gate.cancelled()
    value=source('s');gate.set_result(value)
    assert await pool.inspect('s',lambda:None) is value

@pytest.mark.asyncio
async def test_lru_pins_loading_and_reserved_entries():
    pool=SessionPreparations(1)
    lease=await pool.borrow('a',lambda:source('a'))
    await pool.inspect('b',lambda:source('b'))
    assert pool.has('a') and not pool.has('b')
    lease.dispose();lease.dispose()
    held=await pool.reserve('a',lambda:None,commit)
    await pool.inspect('b',lambda:source('b'))
    await pool.inspect('c',lambda:source('c'))
    assert pool.has('a') and pool.has('c') and not pool.has('b')
    pool.release(held,True)
    assert pool.has('a') and not pool.has('c')

@pytest.mark.asyncio
async def test_reservation_wait_exact_identity_attach_once():
    pool=SessionPreparations();value=source('s')
    held=await pool.reserve('s',lambda:value,commit)
    assert pool.reservation_for(value.session) is held
    with pytest.raises(ValueError,match='cannot publish'):pool.reservation_for(source('s').session)
    with pytest.raises(ValueError,match='reserved'):pool.assert_writable('s')
    waiting=asyncio.create_task(pool.reserve('s',lambda:None,commit));await settle()
    assert not waiting.done()
    pool.release(held,True);next_reservation=await waiting
    assert next_reservation.source is value
    pool.attach(next_reservation)
    with pytest.raises(ValueError):pool.attach(next_reservation)
    pool.discard(held);pool.release(held,True);pool.assert_writable('s')
    assert not pool.has('s')

@pytest.mark.asyncio
async def test_reservation_wait_cancel_does_not_release_owner():
    pool=SessionPreparations();value=source('s');held=await pool.reserve('s',lambda:value,commit)
    abort=AbortController();reason={'kind':'cancel'}
    waiting=asyncio.create_task(pool.reserve('s',lambda:None,commit,abort.signal));await settle();abort.abort(reason)
    with pytest.raises(RuntimeError) as error:await waiting
    assert error.value.reason is reason
    assert pool.reservation_for(value.session) is held
    pool.release(held,False)

@pytest.mark.asyncio
@pytest.mark.parametrize('invalidate',[False,True])
async def test_post_commit_abort_returns_ready_without_reviving_invalidated_entry(invalidate):
    pool=SessionPreparations();abort=AbortController();value=source('s')
    async def finish(v):
        if invalidate:pool.invalidate('s')
        abort.abort(ValueError('after commit'))
        return await commit(v)
    with pytest.raises(ValueError):await pool.reserve('s',lambda:value,finish,abort.signal)
    assert pool.take_ready('s') is (None if invalidate else value)

@pytest.mark.asyncio
async def test_failed_commit_wakes_waiters_without_resurrection():
    pool=SessionPreparations();gate=asyncio.get_running_loop().create_future()
    first=asyncio.create_task(pool.reserve('s',lambda:source('s'),lambda v:gate));await settle()
    second=asyncio.create_task(pool.reserve('s',lambda:None,commit));await settle()
    gate.set_exception(OSError('commit'))
    with pytest.raises(OSError):await first
    assert await second is None and not pool.has('s')

@pytest.mark.asyncio
async def test_invalidated_load_settles_old_observer_but_not_new_entry():
    pool=SessionPreparations();gate=asyncio.get_running_loop().create_future()
    old=asyncio.create_task(pool.inspect('s',lambda:gate));await settle();pool.invalidate('s')
    fresh=source('s');assert await pool.inspect('s',lambda:fresh) is fresh
    stale=source('s');gate.set_result(stale);assert await old is stale
    assert await pool.inspect('s',lambda:None) is fresh

@pytest.mark.asyncio
async def test_python_cancel_during_commit_releases_late_reservation():
    pool=SessionPreparations();gate=asyncio.get_running_loop().create_future();value=source('s')
    job=asyncio.create_task(pool.reserve('s',lambda:value,lambda v:gate));await settle();job.cancel()
    with pytest.raises(asyncio.CancelledError):await job
    gate.set_result({'source':value,'state':{}});await settle()
    assert pool.take_ready('s') is value

@pytest.mark.asyncio
async def test_preaborted_borrow_drops_pin_and_sync_throw_drops_entry():
    pool=SessionPreparations(1);abort=AbortController();abort.abort(ValueError('before'))
    with pytest.raises(ValueError):await pool.borrow('s',lambda:source('s'),abort.signal)
    await settle();await pool.inspect('b',lambda:source('b'))
    assert not pool.has('s')
    def fail():raise OSError('sync')
    with pytest.raises(OSError):await pool.inspect('x',fail)
    assert not pool.has('x')

@pytest.mark.asyncio
async def test_discard_ready_never_disturbs_reserved_source():
    pool=SessionPreparations();value=source('s');held=await pool.reserve('s',lambda:value,commit)
    assert pool.discard_ready('s',value)=='retained'
    assert pool.discard_ready('s',source('s'))=='missing'
    pool.release(held,True)
    assert pool.discard_ready('s',value)=='discarded'

@pytest.mark.asyncio
async def test_abort_cutoff_keeps_started_operation_authoritative():
    abort=AbortController();gate=asyncio.get_running_loop().create_future()
    job=asyncio.create_task(observe_queued_abort(gate,abort.signal,lambda:True));await settle()
    abort.abort(ValueError('ignored'));gate.set_result(42)
    assert await job==42
