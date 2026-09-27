import asyncio
from pathlib import Path
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin, JsonlSessionPersistence
from dsh.session.persistence_sqlite import SqliteSessionPersistencePlugin, SqliteSessionPersistence

@pytest.fixture(params=['jsonl','sqlite'])
def backend(request, tmp_path):
    if request.param == 'jsonl':
        return JsonlSessionPersistencePlugin, {'root':str(tmp_path)}, lambda: JsonlSessionPersistence(str(tmp_path))
    path=str(tmp_path/'sessions.db')
    return SqliteSessionPersistencePlugin, {'path':path}, lambda: SqliteSessionPersistence(path)

async def mount(backend):
    cls, config, fresh=backend
    ctx=Context()
    await ctx.plugin(SessionPlugin)
    fiber=await ctx.plugin(cls, config)
    return ctx, fiber, ctx.get('sessionPersistence')

def turn(session, n=1):
    session.append('turn/start', {'turn':n})
    session.append('turn/end', {'turn':n,'reason':{'kind':'completed'}})

@pytest.mark.asyncio
async def test_failed_write_retains_then_flush_retries(backend):
    ctx,fiber,p=await mount(backend)
    session=ctx.get('sessions').create('s')
    turn(session)
    original=p.append
    async def fail(*args): raise OSError('controlled failure')
    p.append=fail
    try:
        with pytest.raises(OSError): await session.flush()
        assert p._live_writes.live[session]['writes'].has_work
        p.append=original
        turn(session,2)
        await session.flush()
        assert (await p.read_from('s',0)).events == session.events
    finally:
        p.append=original
        await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_unload_drains_and_reload_adopts_open_turn(backend):
    ctx,fiber,p=await mount(backend)
    session=ctx.get('sessions').create('s')
    session.append('turn/start',{'turn':1})
    await fiber.dispose()
    cls,config,_=backend
    second=await ctx.plugin(cls,config)
    p=ctx.get('sessionPersistence')
    session.append('turn/end',{'turn':1,'reason':{'kind':'completed'}})
    try:
        await session.flush()
        assert (await p.read_from('s',0)).events==session.events
        assert len((await p.load('s')).events)==2
    finally:
        await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_mount_adopts_preexisting_seed_and_noop_flush_never_duplicates(backend):
    cls,config,_=backend
    ctx=Context(); await ctx.plugin(SessionPlugin)
    session=ctx.get('sessions').create('s'); turn(session)
    await ctx.plugin(cls,config)
    try:
        await session.flush(); await session.flush()
        assert (await ctx.get('sessionPersistence').read_from('s',0)).events==session.events
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_cancelled_flush_observer_does_not_cancel_write(backend):
    ctx,fiber,p=await mount(backend)
    session=ctx.get('sessions').create('s'); turn(session)
    entered=asyncio.Event(); release=asyncio.Event(); original=p.append
    async def gated(*args):
        entered.set(); await release.wait(); await original(*args)
    p.append=gated
    job=asyncio.create_task(session.flush())
    await asyncio.wait_for(entered.wait(),1)
    job.cancel()
    with pytest.raises(asyncio.CancelledError): await job
    release.set()
    try:
        await session.flush()
        assert (await p.read_from('s',0)).events==session.events
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_new_identity_cannot_overwrite_stored_prefix(backend):
    ctx,fiber,p=await mount(backend)
    old=ctx.get('sessions').create('s'); turn(old)
    await old.flush()
    saved=(await p.read_from('s',0)).events
    # Separate Context models a new application process choosing an occupied ID.
    await ctx.fiber.dispose()
    ctx,fiber,p=await mount(backend)
    fresh=ctx.get('sessions').create('s'); turn(fresh,2)
    try:
        with pytest.raises(ValueError,match='collision'): await fresh.flush()
        assert (await p.read_from('s',0)).events==saved
    finally:
        await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_retiring_identity_drains_before_replacement_claims_prefix(backend):
    ctx,fiber,p=await mount(backend)
    store=ctx.get('sessions')
    old=store.prepare('s')
    detach=store.enter(old);store.announce(old)
    turn(old)
    gate=asyncio.Event();entered=asyncio.Event();original=p.append
    async def gated(*args):
        entered.set();await gate.wait();await original(*args)
    p.append=gated
    detach()
    await asyncio.wait_for(entered.wait(),1)
    new=store.prepare('s',seed=list(old.events),meta=old.header.to_dict())
    store.enter(new);store.announce(new)
    turn(new,2)
    job=asyncio.create_task(new.flush())
    await asyncio.sleep(0)
    assert not job.done()
    gate.set()
    try:
        await job
        assert (await p.read_from('s',0)).events == new.events
        assert p._live_writes.owners['s'] is new
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_jsonl_hmr_truncates_bad_tail_without_closing_live_turn(tmp_path):
    backend=(JsonlSessionPersistencePlugin,{'root':str(tmp_path)},None)
    ctx,fiber,p=await mount(backend)
    session=ctx.get('sessions').create('s')
    session.append('turn/start',{'turn':1})
    await session.flush();path=Path(p.locate(session.header).path)
    await fiber.dispose()
    with path.open('ab') as stream: stream.write(b'{"torn":')
    await ctx.plugin(JsonlSessionPersistencePlugin,{'root':str(tmp_path)})
    session.append('turn/end',{'turn':1,'reason':{'kind':'completed'}})
    try:
        await session.flush()
        assert (await ctx.get('sessionPersistence').read_from('s',0)).events == session.events
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_empty_live_session_is_not_materialized(backend):
    ctx,fiber,p=await mount(backend)
    session=ctx.get('sessions').create('empty')
    try:
        await session.flush()
        with pytest.raises(FileNotFoundError): await p.read_from('empty',0)
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_sqlite_failed_batch_rolls_back_before_retry(tmp_path):
    p=SqliteSessionPersistence(str(tmp_path/'sessions.db'))
    from dsh.core.session import SessionHeader
    await p.create(SessionHeader(session_id='s'))
    p._conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON session_events WHEN NEW.seq=1 BEGIN SELECT RAISE(FAIL, 'controlled failure'); END")
    events=[dict(type='turn/start',seq=n,time=n,data=dict(turn=n+1)) for n in range(2)]
    try:
        with pytest.raises(Exception,match='controlled failure'): await p.append('s',events)
        with pytest.raises(FileNotFoundError): await p.read_stored('s')
        p._conn.execute('DROP TRIGGER fail_second')
        await p.append('s',events)
        assert (await p.read_stored('s')).events == events
    finally: p.close()

@pytest.mark.parametrize('value',[0,True,1.5,2147483648])
def test_invalid_batch_deadline_rejected(value):
    from dsh.session.live_persistence import LivePersistence
    with pytest.raises(TypeError,match='writeBatchMaxDelayMs'):
        LivePersistence(None,None,value)

@pytest.mark.asyncio
async def test_jsonl_fsync_failure_rolls_back_then_retry_writes_once(tmp_path, monkeypatch):
    import os
    from dsh.core.session import SessionHeader
    p=JsonlSessionPersistence(str(tmp_path))
    header=SessionHeader(session_id='s');await p.create(header)
    await p._create(header)  # Exercise rollback of an existing physical header.
    p.storage().states['s']['materialized'] = True
    path=Path(p.locate(header).path);before=path.read_bytes()
    fsync=os.fsync;calls=[]
    def fail_once(fd):
        calls.append(fd)
        if len(calls)==1: raise OSError('fsync failed')
        fsync(fd)
    monkeypatch.setattr(os,'fsync',fail_once)
    events=[dict(type='turn/start',seq=0,time=1,data=dict(turn=1))]
    with pytest.raises(OSError,match='fsync failed'):await p.append('s',events)
    assert path.read_bytes()==before
    await p.append('s',events)
    assert (await p.read_from('s',0)).events==events

@pytest.mark.asyncio
async def test_retirement_and_backend_unload_share_exact_drain_state(backend):
    ctx,fiber,p=await mount(backend)
    store=ctx.get('sessions');session=store.prepare('s')
    detach=store.enter(session);store.announce(session);turn(session)
    await session.flush()
    detach()
    try:
        await p._live_writes.dispose()
        assert not p._live_writes.live
    finally: await ctx.fiber.dispose()
