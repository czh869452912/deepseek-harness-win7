import asyncio
import copy
import pytest
from dsh.core.session import SessionHeader
from dsh.core.abort import AbortController
from test_session_live_persistence import backend, mount, turn

async def persisted(backend):
    ctx,fiber,p=await mount(backend)
    await p.create(SessionHeader(session_id='s'))
    await p.append('s',[dict(type='turn/start',seq=0,time=1,data=dict(turn=1)),
                       dict(type='turn/end',seq=1,time=2,data=dict(turn=1,reason=dict(kind='completed')))])
    return ctx,fiber,p

@pytest.mark.asyncio
async def test_prepare_reuses_exact_session_and_release_mutation_discards(backend):
    ctx,fiber,p=await persisted(backend)
    try:
        first=await p.prepare('s');session=first.session;first.dispose()
        second=await p.prepare('s');assert second.session is session
        second.session.append('turn/start',{'turn':2});second.dispose()
        third=await p.prepare('s');assert third.session is not session
        assert len(third.session.events)==3
        assert third.session.events[-1]["type"]=="session/end-seed";third.dispose()
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_reserved_identity_blocks_writes_and_load_waits(backend):
    ctx,fiber,p=await persisted(backend)
    held=await p.prepare('s')
    try:
        await p.append('s',[])
        with pytest.raises(ValueError,match='reserved'):await p.append('s',[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
        with pytest.raises(ValueError,match='reserved'):await p.create(SessionHeader(session_id='s'))
        loaded=asyncio.create_task(p.load('s'));await asyncio.sleep(0);await asyncio.sleep(0)
        assert not loaded.done()
        held.dispose();assert len((await loaded).events)==2
    finally:held.dispose();await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_cache_reloads_after_public_append_and_detaches_inspection(backend):
    ctx,fiber,p=await persisted(backend)
    try:
        old=await p.inspect('s');old.events.clear()
        assert len((await p.inspect('s')).events)==2
        await p.append('s',[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
        fresh=await p.inspect('s');assert len(fresh.events)==4
        assert len((await p.read_from('s',0)).events)==3
        held=await p.prepare('s');assert len(held.session.events)==5;held.dispose()
        assert len((await p.read_from('s',0)).events)==4
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_concurrent_inspection_shares_load_and_observer_abort(backend):
    ctx,fiber,p=await persisted(backend);original=p._inspect_unshared
    gate=asyncio.Event();entered=asyncio.Event();calls=[]
    async def blocked(sid):
        calls.append(sid);entered.set();await gate.wait();return await original(sid)
    p._inspect_unshared=blocked
    abort=AbortController()
    a=asyncio.create_task(p.inspect('s',abort.signal));await entered.wait()
    b=asyncio.create_task(p.inspect('s'));abort.abort(ValueError('cancel'))
    try:
        with pytest.raises(ValueError):await a
        gate.set();assert len((await b).events)==2 and calls==['s']
    finally:gate.set();await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_exact_reserved_session_publishes_and_persists_unpublished_suffix(backend):
    ctx,fiber,p=await persisted(backend);held=await p.prepare('s')
    session=held.session;turn(session,2)
    store=ctx.get('sessions');store.enter(session);store.announce(session);held.dispose()
    try:
        await session.flush()
        assert (await p.read_from('s',0)).events==session.events
        with pytest.raises(ValueError,match='live'):await p.prepare('s')
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_revision_change_between_inspection_and_reserve_reloads(backend):
    ctx,fiber,p=await persisted(backend)
    try:
        await p.inspect('s')
        # Simulate a different writer bypassing this coordinator's invalidation.
        await p._append('s',[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
        held=await p.prepare('s')
        assert len(held.session.events)==5;held.dispose()
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_abort_queued_repair_does_not_modify_durable_tail(backend):
    ctx,fiber,p=await persisted(backend)
    await p.append('s',[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
    lock=p.storage_lock('s');await lock.acquire();abort=AbortController()
    job=asyncio.create_task(p.prepare('s',abort.signal))
    for _ in range(20):await asyncio.sleep(0)
    abort.abort(ValueError('queued repair cancelled'));lock.release()
    try:
        with pytest.raises(ValueError):await job
        assert len((await p.read_from('s',0)).events)==3
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_public_append_snapshots_before_waiting_for_storage_lock(backend):
    ctx,fiber,p=await persisted(backend)
    lock=p.storage_lock('s');await lock.acquire()
    batch=[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))]
    job=asyncio.create_task(p.append('s',batch));await asyncio.sleep(0)
    batch[0]['data']['turn']=99;lock.release()
    try:
        await job
        assert (await p.read_from('s',2)).events[0]['data']['turn']==2
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_public_append_rejects_lossy_json_without_writing(backend):
    ctx,fiber,p=await persisted(backend)
    try:
        with pytest.raises(TypeError):
            await p.append('s',[dict(type='turn/start',seq=2,time=3,data=dict(turn=float('nan')))])
        assert len((await p.read_from('s',0)).events)==2
    finally:await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_unload_invalidates_held_reservation_and_wakes_waiter(backend):
    ctx,fiber,p=await persisted(backend);held=await p.prepare('s')
    waiting=asyncio.create_task(p.prepare('s'))
    for _ in range(6):await asyncio.sleep(0)
    await fiber.dispose()
    with pytest.raises(RuntimeError,match='closed'):await asyncio.wait_for(waiting,1)
    held.dispose()
    assert not p.prepared().pool.entries
    await ctx.fiber.dispose()
