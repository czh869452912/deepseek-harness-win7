import asyncio
import os
import stat
import uuid

from dsh.session.sqlite_schema import sql, open_database, decode_store_identity, decode_session_row, decode_event_row, row_to_meta, validate_mutation
from dsh.session.sqlite_codec import pack_chunk_runs, MAX_PACKED_ROW_MEMBERS
from dsh.session.sqlite_compression import bind_record, decode_row, scan_rows
from dsh.session.file_revision import filesystem_identity
from dsh.session.preparations import throw_aborted


class SqliteRollbackError(RuntimeError):
    def __init__(self, operation, original, rollback):
        super().__init__('session-persistence-sqlite %s failed and rollback also failed' % operation)
        self.name = 'AggregateError'
        self.errors = [original, rollback]


class SqliteStore:
    name = 'session-persistence-sqlite'

    def __init__(self, path, journal_mode='wal', busy_timeout_ms=5000):
        self.path = path
        self.journal_mode = journal_mode
        self.busy_timeout_ms = busy_timeout_ms
        self.database = None
        self.path_job = None
        self.open_job = None
        self.opened = False
        self.store_identity = None

    async def validate_path(self):
        if self.path_job is None:
            self.path_job = asyncio.ensure_future(self.prepare_path())
        await asyncio.shield(self.path_job)

    async def prepare_path(self):
        self.database_path = self.path if self.path == ':memory:' else os.path.abspath(self.path)
        if self.database_path != ':memory:':
            parent = os.path.dirname(self.database_path)
            os.makedirs(parent, mode=0o700, exist_ok=True)
            info = os.lstat(parent)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('session database parent "%s" must be a real directory' % parent)
            current_uid = getattr(os, 'getuid', lambda: None)()
            if current_uid is not None and (info.st_uid != current_uid or info.st_mode & 0o022):
                raise ValueError('session database parent "%s" must be owned by the current user and not group/world-writable' % parent)
            self.validate_file(present=True)

    def validate_file(self, present=False):
        try:
            info = os.lstat(self.database_path)
        except FileNotFoundError:
            if present:
                return
            raise
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError('session database "%s" must be a regular file, not a symbolic link' % self.database_path)
        current_uid = getattr(os, 'getuid', lambda: None)()
        if current_uid is not None and (info.st_uid != current_uid or info.st_mode & 0o077):
            raise ValueError('session database "%s" must be owned by the current user and accessible only by that user' % self.database_path)

    async def open(self):
        if self.open_job is None:
            self.open_job = asyncio.ensure_future(self.open_database())
        await asyncio.shield(self.open_job)

    async def open_database(self):
        await self.validate_path()
        if self.database_path != ':memory:':
            try:
                descriptor = os.open(self.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
            self.validate_file()
        self.database = await open_database(self.database_path, self.journal_mode, self.busy_timeout_ms)
        try:
            row = self.database.prepare(sql('select-store-id')).get()
            if row is None:
                raise ValueError('session database at "%s" has no valid store identity' % self.database_path)
            try:
                identity = decode_store_identity(row)
            except Exception as error:
                raise ValueError('session database at "%s" has no valid store identity' % self.database_path) from error
            if self.database_path == ':memory:':
                self.store_identity = 'memory:store:' + identity
            else:
                info = filesystem_identity(self.database_path)
                self.store_identity = 'file:%s:%s:%s:store:%s' % (info['dev'], info['ino'], info['birthtimeNs'], identity)
            self.opened = True
        except BaseException:
            self.database.close()
            raise

    async def observe(self, signal=None):
        throw_aborted(signal)
        await self.open()
        throw_aborted(signal)

    def transaction(self, operation, mutation=False, label='read'):
        self.database.exec(sql('begin-immediate' if mutation else 'begin'))
        try:
            if mutation:
                validate_mutation(self.database, self.database_path)
            value = operation()
            self.database.exec(sql('commit'))
            return value
        except BaseException as error:
            try:
                self.database.exec(sql('rollback'))
            except BaseException as rollback:
                raise SqliteRollbackError(label, error, rollback) from error
            raise

    def row_for(self, identity):
        row = self.database.prepare(sql('select-session')).get(identity)
        return decode_session_row(row) if row is not None else None

    def session_key(self, identity):
        row = self.database.prepare(sql('select-session-key')).get(identity)
        if row is None:
            raise ValueError('session %s metadata row is missing' % identity)
        return row['id']

    def revision(self, row):
        return '%s:incarnation:%s:revision:%s' % (self.store_identity, row['incarnation'], row['revision'])

    async def load_stored(self, identity, signal=None):
        await self.observe(signal)
        def read():
            row = self.row_for(identity)
            if row is None:
                return None
            physical = self.database.prepare(sql('select-events')).all(self.session_key(identity))
            return row, [decode_event_row(value) for value in physical]
        snapshot = self.transaction(read)
        throw_aborted(signal)
        if snapshot is None:
            return None
        row, physical = snapshot
        scanned = scan_rows(physical)
        return dict(meta=row_to_meta(row), events=scanned['preserved'], revision=self.revision(row),
                    **(dict(tornMarker=scanned['tornFrom']) if 'tornFrom' in scanned else {}))

    async def read_revision(self, identity, signal=None):
        await self.observe(signal)
        row = self.row_for(identity)
        throw_aborted(signal)
        return self.revision(row) if row is not None else None

    def physical_span_from(self, key, sequence):
        floor = max(0, sequence - MAX_PACKED_ROW_MEMBERS + 1)
        predecessors = self.database.prepare(sql('select-packed-predecessors')).all(key, floor, sequence)
        base = sequence
        for value in predecessors:
            row = decode_event_row(value)
            try:
                events = decode_row(row)
                if events and events[-1]['seq'] >= sequence:
                    base = min(base, row['seq'])
            except Exception:
                base = min(base, row['seq'])
        rows = self.database.prepare(sql('select-events-from')).all(key, base)
        return base, [decode_event_row(value) for value in rows]

    async def load_stored_from(self, identity, sequence, signal=None):
        await self.observe(signal)
        def read():
            row = self.row_for(identity)
            if row is None:
                return None
            return row, self.physical_span_from(self.session_key(identity), sequence)
        snapshot = self.transaction(read)
        throw_aborted(signal)
        if snapshot is None:
            return None
        row, (base, physical) = snapshot
        scanned = scan_rows(physical, base)
        return dict(meta=row_to_meta(row), events=[event for event in scanned['preserved'] if event['seq'] >= sequence])

    def write_row(self, meta):
        values = [meta.get(name) for name in ('id', 'version', 'createdAt', 'cwd', 'parentSession', 'seedLength',
                                             'origin', 'delegationDepth', 'agentPreset')]
        return self.database.prepare(sql('upsert-session')).get(*(values + [str(uuid.uuid4())]))['id']

    def tail_rows(self, key):
        tail = self.database.prepare(sql('select-tail-events')).all(key, 2)
        tail.reverse()
        return [] if not tail else self.physical_span_from(key, tail[0]['seq'])[1]

    def logical_last(self, identity, rows):
        if not rows:
            return None
        scanned = scan_rows(rows, rows[0]['seq'])
        if 'tornFrom' in scanned:
            raise ValueError('session %s has an invalid physical tail at seq %s' % (identity, scanned['tornFrom']))
        return scanned['preserved'][-1] if scanned['preserved'] else None

    def insert(self, key, record):
        self.database.prepare(sql('insert-event')).run(key, *[record[name] for name in
            ('seq', 'type', 'time', 'data', 'source_event_seqs', 'surface_op', 'is_packed')])

    def increment_revision(self, identity):
        value = self.database.prepare(sql('update-session-revision')).run(identity)
        if value['changes'] != 1:
            raise ValueError('session %s metadata row is missing' % identity)

    async def append_batch(self, meta, events, materialized):
        await self.open()
        if not events:
            return
        def append():
            key = self.session_key(meta['id']) if materialized else self.write_row(meta)
            last = self.logical_last(meta['id'], self.tail_rows(key))
            expected = 0 if last is None else last['seq'] + 1
            if events[0]['seq'] != expected:
                raise ValueError('session %s append starts at seq %s, stored next seq is %s' % (meta['id'], events[0]['seq'], int(expected)))
            for record in pack_chunk_runs(events):
                self.insert(key, bind_record(record))
            self.increment_revision(meta['id'])
        self.transaction(append, mutation=True, label='append')

    async def materialize_header(self, meta):
        await self.open()
        self.transaction(lambda: self.write_row(meta), mutation=True, label='materialize empty session')

    async def commit_repair(self, meta, torn_marker, closers):
        await self.open()
        if torn_marker is None and not closers:
            return
        def repair():
            key = self.session_key(meta['id'])
            rows = self.database.prepare(sql('select-events')).all(key)
            current = scan_rows([decode_event_row(value) for value in rows])
            if torn_marker is not None:
                if current.get('tornFrom') != torn_marker:
                    raise ValueError('session %s repair is stale: physical tail no longer starts at seq %s' % (meta['id'], torn_marker))
                self.database.prepare(sql('delete-events-from')).run(key, torn_marker)
            elif 'tornFrom' in current:
                raise ValueError('session %s repair omitted current torn tail at seq %s' % (meta['id'], current['tornFrom']))
            if closers:
                expected = current['preserved'][-1]['seq'] + 1 if current['preserved'] else 0
                if closers[0]['seq'] != expected:
                    raise ValueError('session %s repair is stale: closer starts at seq %s, stored next seq is %s' % (meta['id'], closers[0]['seq'], int(expected)))
                for closer in closers:
                    self.insert(key, bind_record(closer))
            self.increment_revision(meta['id'])
        self.transaction(repair, mutation=True, label='repair')

    async def list(self, signal=None):
        await self.observe(signal)
        rows = [decode_session_row(value) for value in self.database.prepare(sql('select-sessions')).all()]
        throw_aborted(signal)
        return [row_to_meta(row) for row in rows]

    async def list_snapshots(self, signal=None):
        await self.observe(signal)
        rows = [decode_session_row(value) for value in self.database.prepare(sql('select-sessions')).all()]
        throw_aborted(signal)
        return [dict(header=row_to_meta(row), revision=self.revision(row)) for row in rows]

    async def close(self):
        if self.open_job is None:
            if self.path_job is not None:
                await asyncio.gather(self.path_job, return_exceptions=True)
            return
        await asyncio.gather(self.open_job, return_exceptions=True)
        if self.opened:
            self.opened = False
            self.database.close()
