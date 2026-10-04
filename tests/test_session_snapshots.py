import json
import os
import sqlite3

import pytest

from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.session.persistence_sqlite import SqliteSessionPersistence
from test_session_live_persistence import backend
from test_prepared_persistence import persisted


@pytest.mark.asyncio
async def test_actual_durable_snapshot_revisions_track_owned_batches_and_reopen(backend):
    context, _, persistence = await persisted(backend)
    try:
        original = (await persistence.listSnapshots())[0]
        original.header.created_at = -1
        unchanged = (await persistence.listSnapshots())[0]
        assert unchanged.header.created_at != -1 and original.revision == unchanged.revision
        await persistence.append('s', [])
        assert (await persistence.listSnapshots())[0].revision == original.revision
        await persistence.append('s', [dict(type='turn/start', seq=2, time=3, data=dict(turn=2)),
            dict(type='turn/end', seq=3, time=4, data=dict(turn=2, reason=dict(kind='completed')))])
        changed = (await persistence.listSnapshots())[0]
        assert changed.revision != original.revision
        assert context.get('sessions').get('s') is None
        await context.fiber.dispose()
        fresh = backend[2]()
        try:
            assert (await fresh.listSnapshots())[0].revision == changed.revision
        finally:
            if isinstance(fresh, SqliteSessionPersistence):
                fresh.close()
    finally:
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_durable_snapshot_preabort_has_exact_reason_without_listing(backend, monkeypatch):
    context, _, persistence = await persisted(backend)
    controller = AbortController()
    reason = TypeError('snapshot deadline')
    controller.abort(reason)
    accessed = []
    async def list_failure(signal=None):
        accessed.append(signal)
        raise AssertionError('snapshot accessed provider after preabort')
    monkeypatch.setattr(persistence, 'list', list_failure)
    try:
        with pytest.raises(TypeError) as failure:
            await persistence.listSnapshots(controller.signal)
        assert failure.value is reason and accessed == []
    finally:
        await context.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('missing,abort', [(False, False), (True, False), (False, True), (True, True)])
async def test_jsonl_snapshot_stat_failure_and_abort_priority(tmp_path, monkeypatch, missing, abort):
    from dsh.session.persistence_jsonl import JsonlSessionPersistence
    import dsh.session.file_revision as revisions
    persistence = JsonlSessionPersistence(str(tmp_path))
    header = SessionHeader(session_id='s')
    controller = AbortController()
    reason = TypeError('caller aborted stat')
    stat_error = FileNotFoundError('removed log') if missing else PermissionError('protected log')
    signals = []
    async def listed(signal=None):
        signals.append(signal)
        return [header]
    monkeypatch.setattr(persistence, 'list', listed)
    monkeypatch.setattr(persistence, '_find_log_path', lambda identity: str(tmp_path / 's.jsonl'))
    def stat_failure(path):
        if abort:
            controller.abort(reason)
        raise stat_error
    monkeypatch.setattr(revisions, 'file_revision', stat_failure)
    if missing and not abort:
        assert await persistence.listSnapshots(controller.signal) == []
    else:
        with pytest.raises(type(reason if abort else stat_error)) as failure:
            await persistence.listSnapshots(controller.signal)
        assert failure.value is (reason if abort else stat_error)
    assert signals == [controller.signal]


def legacy_database(path):
    with sqlite3.connect(str(path)) as connection:
        connection.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, version INTEGER, created_at INTEGER, '
            'cwd TEXT, parent_session TEXT, seed_length INTEGER, meta_json TEXT)')
        header = SessionHeader(session_id='legacy', created_at=1)
        connection.execute('INSERT INTO sessions VALUES (?,0,1,NULL,NULL,NULL,?)',
            ('legacy', json.dumps(header.to_dict())))


@pytest.mark.asyncio
async def test_sqlite_revision_upgrade_preserves_existing_header_and_incarnation(tmp_path):
    path = tmp_path / 'legacy.db'
    legacy_database(path)
    first = SqliteSessionPersistence(str(path))
    try:
        original = (await first.listSnapshots())[0]
        assert original.header.id == 'legacy'
        assert original.revision.endswith(':revision:0')
    finally:
        first.close()
    second = SqliteSessionPersistence(str(path))
    try:
        assert (await second.listSnapshots())[0].revision == original.revision
    finally:
        second.close()


def test_failed_sqlite_revision_upgrade_rolls_back_ddl_and_backfill(tmp_path, monkeypatch):
    import dsh.session.persistence_sqlite as provider
    path = tmp_path / 'legacy.db'
    legacy_database(path)
    calls = []
    original_uuid = provider.uuid.uuid4
    failure = RuntimeError('incarnation allocation failed')
    def fail_backfill():
        calls.append(True)
        if len(calls) == 2:
            raise failure
        return original_uuid()
    monkeypatch.setattr(provider.uuid, 'uuid4', fail_backfill)
    with pytest.raises(RuntimeError) as caught:
        SqliteSessionPersistence(str(path))
    assert caught.value is failure
    with sqlite3.connect(str(path)) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(sessions)')}
        assert 'incarnation' not in columns and 'revision' not in columns
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN ('session_store_identity','session_events')").fetchall() == []
        assert connection.execute('SELECT id FROM sessions').fetchall() == [('legacy',)]


@pytest.mark.asyncio
async def test_failed_sqlite_event_batch_rolls_back_revision_with_event_suffix(tmp_path):
    persistence = SqliteSessionPersistence(str(tmp_path / 'events.db'))
    try:
        await persistence._create(SessionHeader(session_id='s'))
        await persistence._append('s', [dict(type='session/end-seed', seq=0, time=1, data={})])
        original = (await persistence.listSnapshots())[0].revision
        with pytest.raises(sqlite3.IntegrityError):
            await persistence._append('s', [dict(type='turn/start', seq=1, time=2, data=dict(turn=1)),
                dict(type='turn/start', seq=0, time=3, data=dict(turn=2))])
        assert (await persistence.listSnapshots())[0].revision == original
        assert persistence._conn.execute('SELECT seq FROM session_events').fetchall() == [(0,)]
    finally:
        persistence.close()


def test_windows_file_revision_handles_are_closed_after_success_and_stat_failure(tmp_path):
    from dsh.session.file_revision import file_revision, filesystem_identity
    path = tmp_path / 'revision.txt'
    path.write_text('owned', encoding='utf-8')
    identity = filesystem_identity(str(path))
    observed = os.stat(str(path))
    assert identity['dev'] == observed.st_dev and identity['ino'] == observed.st_ino
    assert identity['size'] == 5 and identity['mtimeNs'] == observed.st_mtime_ns
    first = file_revision(str(path))
    for index in range(100):
        assert file_revision(str(path)) == first
    moved = tmp_path / 'moved.txt'
    path.rename(moved)
    with pytest.raises(FileNotFoundError):
        file_revision(str(path))
    moved.unlink()


@pytest.mark.asyncio
async def test_two_sqlite_instances_observe_same_namespace_and_atomic_revision(tmp_path):
    path = str(tmp_path / 'shared.db')
    first = SqliteSessionPersistence(path)
    second = SqliteSessionPersistence(path)
    try:
        await first._create(SessionHeader(session_id='s'))
        original = (await first.listSnapshots())[0].revision
        assert (await second.listSnapshots())[0].revision == original
        await second._append('s', [dict(type='session/end-seed', seq=0, time=1, data={})])
        changed = (await first.listSnapshots())[0].revision
        assert changed != original and (await second.listSnapshots())[0].revision == changed
    finally:
        first.close()
        second.close()


def test_windows_file_revision_supports_long_unicode_paths_without_os_patches(tmp_path):
    if os.name != 'nt':
        return
    from dsh.session.file_revision import file_revision
    import shutil
    directory = str(tmp_path / ('迁移' * 30) / ('快照' * 30) / ('修订' * 30))
    extended = '\\\\?\\' + directory
    os.makedirs(extended)
    path = directory + '\\owned.txt'
    try:
        with open('\\\\?\\' + path, 'w', encoding='utf-8') as stream:
            stream.write('owned')
        assert len(path) > 260
        token = file_revision(path)
        assert token.split(':')[2] == '5'
        os.remove('\\\\?\\' + path)
    finally:
        shutil.rmtree(extended)
