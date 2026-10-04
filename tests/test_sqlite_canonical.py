import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis import Context
from dsh.core.session import SessionPlugin, SessionHeader
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistencePlugin
from dsh.session.sqlite_database import SqliteDatabase, DatabaseError
from dsh.session.sqlite_sql import sql, SQL_RESOURCES
from dsh.session.sqlite_store import SqliteStore, SqliteRollbackError


def chunk(sequence):
    return dict(type='assistant/chunk', seq=sequence, time=sequence,
                data=dict(turn=1, step=1, chunk=dict(type='text-delta', index=0, text='界' * 100)))


def test_canonical_registry_and_unchanged_closed_sql_resources():
    from dsh.session import SqliteSessionPersistencePlugin as PublicPlugin
    root = Path(__file__).resolve().parents[1]
    assert resolve_harness_plugin('@deepseek-ai/dsh-session-persistence-sqlite') is SqliteSessionPersistencePlugin
    assert PublicPlugin is SqliteSessionPersistencePlugin
    source = root / 'reference/packages/session/session-persistence-sqlite/resources/sql'
    assert {path.stem for path in source.glob('*.sql')} == set(SQL_RESOURCES)
    for name in SQL_RESOURCES:
        native = root / 'dsh/session/resources/sql' / (name + '.sql')
        assert native.read_bytes() == (source / (name + '.sql')).read_bytes()
        assert sql(name) == native.read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='Unknown SQLite resource'):
        sql('../schema')


@pytest.mark.asyncio
async def test_actual_lazy_store_packed_seek_and_detached_revision(tmp_path):
    path = tmp_path / 'nested/sessions.db'
    store = SqliteStore(str(path))
    metadata = dict(id='packed', version=0, createdAt=1)
    await store.validate_path()
    assert path.parent.is_dir() and not path.exists()
    try:
        await store.append_batch(metadata, [chunk(sequence) for sequence in range(2051)], False)
        physical = store.database.prepare('SELECT seq, typeof(data) AS kind FROM events').all()
        assert physical == [dict(seq=0, kind='blob'), dict(seq=1024, kind='blob'), dict(seq=2048, kind='blob')]
        before = await store.read_revision('packed')
        detached = await store.load_stored('packed')
        suffix = await store.load_stored_from('packed', 1025)
        assert suffix['events'] == detached['events'][1025:]
        await store.append_batch(metadata, [chunk(2051)], True)
        assert int((await store.read_revision('packed')).rsplit(':', 1)[1]) == int(before.rsplit(':', 1)[1]) + 1
        assert len(detached['events']) == 2051
        with pytest.raises(ValueError, match='stored next seq is 2052'):
            await store.append_batch(metadata, [chunk(2051)], True)
        assert len((await store.load_stored('packed'))['events']) == 2052
    finally:
        await store.close()
    reopened = SqliteStore(str(path))
    try:
        assert len((await reopened.load_stored('packed'))['events']) == 2052
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_canonical_plugin_cold_torn_repair_and_unpublished_end_seed(tmp_path):
    path = tmp_path / 'sessions.db'
    first = Context()
    second = Context()
    await first.plugin(SessionPlugin)
    await first.plugin(SqliteSessionPersistencePlugin, dict(path=str(path)))
    assert not path.exists()
    persistence = first.get('sessionPersistence')
    metadata = SessionHeader('cold', created_at=1234, cwd=str(tmp_path))
    events = [dict(type='turn/start', seq=0, time=0, data=dict(turn=1)),
              dict(type='step/start', seq=1, time=1, data=dict(turn=1, step=1))]
    events.extend(chunk(sequence) for sequence in range(2, 102))
    try:
        await persistence.create(metadata)
        await persistence.append(metadata.id, events)
        key = persistence.store.session_key(metadata.id)
        persistence.store.database.prepare(sql('insert-event')).run(key, 102, 'text-chunks', 102, '{invalid', None, None, 1)
        before = await persistence.stored_revision(metadata.id)
        assert len((await persistence.inspect(metadata.id)).events) == 104
        assert await persistence.stored_revision(metadata.id) == before
        assert len((await persistence.load(metadata.id)).events) == 104
        assert await persistence.stored_revision(metadata.id) != before
        await first.fiber.dispose()
        await second.plugin(SessionPlugin)
        await second.plugin(SqliteSessionPersistencePlugin, dict(path=str(path)))
        restored = second.get('sessionPersistence')
        reservation = await restored.prepare(metadata.id)
        try:
            assert len(reservation.session.events) == 105
            assert reservation.session.events[-1]['type'] == 'session/end-seed'
            assert second.get('sessions').get(metadata.id) is None
            assert len((await restored.read_stored(metadata.id)).events) == 104
            assert len((await restored.read_from(metadata.id, 50)).events) == 54
        finally:
            reservation.dispose()
    finally:
        await first.fiber.dispose()
        await second.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('setup', ['CREATE TABLE legacy(value TEXT)', 'PRAGMA user_version=18',
    'PRAGMA user_version=20', 'PRAGMA user_version=19; PRAGMA application_id=12345',
    'PRAGMA user_version=19; PRAGMA application_id=1146308688; CREATE TABLE legacy(value TEXT)'],
    ids=['unversioned', 'old', 'future', 'foreign', 'altered'])
async def test_foreign_layout_refusal_preserves_actual_file_and_closes_handle(tmp_path, setup):
    path = tmp_path / 'foreign.db'
    database = SqliteDatabase(str(path))
    database.exec(setup)
    database.close()
    original = path.read_bytes()
    store = SqliteStore(str(path))
    with pytest.raises(ValueError):
        await store.open()
    await store.close()
    assert path.read_bytes() == original and not store.opened
    path.rename(tmp_path / 'retained.db')


@pytest.mark.asyncio
async def test_existing_page_size_and_revision_survive_reopen(tmp_path):
    path = tmp_path / 'page.db'
    store = SqliteStore(str(path), journal_mode='delete')
    await store.materialize_header(dict(id='page', version=0, createdAt=1))
    before = await store.read_revision('page')
    await store.close()
    database = SqliteDatabase(str(path))
    database.exec('PRAGMA page_size=4096; VACUUM')
    database.close()
    reopened = SqliteStore(str(path), journal_mode='delete')
    try:
        await reopened.open()
        assert reopened.database.prepare('PRAGMA page_size').get()['page_size'] == 4096
        assert await reopened.read_revision('page') == before
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_current_mutation_ownership_rechecked_before_writing():
    store = SqliteStore(':memory:')
    metadata = dict(id='owned', version=0, createdAt=1)
    try:
        await store.append_batch(metadata, [chunk(0)], False)
        revision = await store.read_revision(metadata['id'])
        store.database.exec('PRAGMA user_version=20')
        with pytest.raises(ValueError, match='schema changed before mutation'):
            await store.append_batch(metadata, [chunk(1)], True)
        assert await store.read_revision(metadata['id']) == revision
        store.database.exec(sql('set-user-version-19'))
        await store.append_batch(metadata, [chunk(1)], True)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_open(tmp_path, monkeypatch):
    from dsh.session import sqlite_store
    real_open = sqlite_store.open_database
    entered, released = asyncio.Event(), asyncio.Event()
    async def paused(*arguments):
        entered.set()
        await released.wait()
        return await real_open(*arguments)
    monkeypatch.setattr(sqlite_store, 'open_database', paused)
    store = SqliteStore(str(tmp_path / 'shared.db'))
    cancelled = asyncio.ensure_future(store.open())
    await entered.wait()
    remaining = asyncio.ensure_future(store.open())
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert not store.open_job.cancelled()
    released.set()
    await remaining
    await store.close()
    assert not store.database._handle


@pytest.mark.asyncio
async def test_empty_mutations_and_missing_materialization_are_inert():
    store = SqliteStore(':memory:')
    metadata = dict(id='empty', version=0, createdAt=1)
    try:
        await store.append_batch(metadata, [], False)
        await store.commit_repair(metadata, None, [])
        assert await store.list() == []
        with pytest.raises(ValueError, match='metadata row is missing'):
            await store.append_batch(metadata, [chunk(0)], True)
        assert await store.list() == []
        await store.materialize_header(metadata)
        revision = await store.read_revision(metadata['id'])
        await store.materialize_header(metadata)
        assert await store.read_revision(metadata['id']) == revision
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['zero-budget', 'non-busy', 'cutoff'])
async def test_failed_journal_attempt_preserves_budget_and_retires_real_handle(monkeypatch, mode):
    from dsh.session import sqlite_schema
    instances = []
    class FailingDatabase(SqliteDatabase):
        def __init__(self, path):
            super().__init__(path)
            self.attempts = 0
            instances.append(self)
        def prepare(self, statement):
            if statement == sql('journal-mode-wal'):
                self.attempts += 1
                raise DatabaseError('controlled journal failure', 6 if mode == 'non-busy' else 5)
            return super().prepare(statement)
    monkeypatch.setattr(sqlite_schema, 'SqliteDatabase', FailingDatabase)
    if mode == 'cutoff':
        ticks = iter([0, 0.05, 0.1])
        monkeypatch.setattr(sqlite_schema, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(DatabaseError, match='controlled journal failure'):
        await sqlite_schema.open_database(':memory:', busy_timeout_ms=0 if mode == 'zero-budget' else 100)
    assert len(instances) == 1 and instances[0].attempts == 1 and not instances[0]._handle


@pytest.mark.asyncio
async def test_busy_journal_retry_reuses_real_handle_and_keeps_security(monkeypatch):
    from dsh.session import sqlite_schema
    class BusyOnceDatabase(SqliteDatabase):
        def __init__(self, path):
            super().__init__(path)
            self.attempts = 0
        def prepare(self, statement):
            if statement == sql('journal-mode-wal'):
                self.attempts += 1
                if self.attempts == 1:
                    raise DatabaseError('controlled busy journal', 5)
            return super().prepare(statement)
    monkeypatch.setattr(sqlite_schema, 'SqliteDatabase', BusyOnceDatabase)
    database = await sqlite_schema.open_database(':memory:', busy_timeout_ms=100)
    try:
        assert database.attempts == 2
        assert database.prepare(sql('select-trusted-schema')).get()['trusted_schema'] == 0
        assert database.prepare(sql('select-synchronous')).get()['synchronous'] == 2
    finally:
        database.close()


@pytest.mark.asyncio
async def test_failed_transaction_and_rollback_keep_both_causes(monkeypatch):
    store = SqliteStore(':memory:')
    await store.open()
    original = ValueError('primary failure')
    rollback = DatabaseError('rollback failure', 10)
    execute = store.database.exec
    def failing(statement):
        if statement == sql('rollback'):
            raise rollback
        return execute(statement)
    monkeypatch.setattr(store.database, 'exec', failing)
    def operation():
        raise original
    try:
        with pytest.raises(SqliteRollbackError) as caught:
            store.transaction(operation, mutation=True, label='append')
        assert str(caught.value) == 'session-persistence-sqlite append failed and rollback also failed'
        assert caught.value.errors == [original, rollback]
    finally:
        await store.close()
