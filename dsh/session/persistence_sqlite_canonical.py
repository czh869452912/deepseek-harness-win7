from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.session.persistence import SessionPersistence, SessionInspection, SessionPersistenceSnapshot
from dsh.session.sqlite_logical import validate_inspection, needs_legacy_prefix, header_from_stored, SessionPersistenceNotFoundError, SessionPersistenceCorruptionError
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.repair import interrupted_turn_closers
from dsh.session.sqlite_store import SqliteStore


class SqliteSessionPersistence(SessionPersistence):
    supports_raw_artifacts = False
    name = 'session-persistence-sqlite'

    def __init__(self, path, ctx=None, journal_mode='wal', busy_timeout_ms=5000):
        super().__init__(ctx)
        self.store = SqliteStore(path, journal_mode, busy_timeout_ms)
        self._live_writes = None

    def locate(self, meta):
        return None

    async def create(self, meta):
        await self.storage().create(meta)

    async def append(self, identity, events):
        await self.storage().append(identity, events)

    async def append_batch(self, meta, events, materialized):
        await self.store.append_batch(meta.to_dict(), events, materialized)

    async def _create(self, meta):
        await self.store.materialize_header(meta.to_dict())

    async def ensure_materialized(self, session):
        await self.storage().ensure_materialized(session)

    async def read_stored(self, identity):
        stored = await self.store.load_stored(identity)
        if stored is None:
            raise SessionPersistenceNotFoundError(identity)
        inspection = SessionInspection(header_from_stored(stored['meta']), stored['events'])
        return validate_inspection(inspection, identity)

    async def stored_revision(self, identity):
        return await self.store.read_revision(identity)

    def _live_session(self, identity):
        sessions = self.ctx.get('sessions') if self.ctx is not None else None
        return sessions.get(identity) if sessions is not None else None

    async def repair_tail(self, identity):
        stored = await self.store.load_stored(identity)
        if stored is not None and 'tornMarker' in stored:
            await self.store.commit_repair(stored['meta'], stored['tornMarker'], [])

    async def _inspect_unshared(self, identity):
        live = self._live_session(identity)
        if live is not None:
            return SessionInspection(live.header, list(live.events))
        stored = await self.store.load_stored(identity)
        inspection, closers = self._validate_cold(stored, identity)
        inspection.events.extend(closers)
        return inspection

    def _validate_cold(self, stored, identity):
        if stored is None:
            raise SessionPersistenceNotFoundError(identity)
        try:
            inspection = validate_inspection(SessionInspection(header_from_stored(stored['meta']), stored['events']), identity)
            from dsh.core.session.types import validate_restored_session_header
            inspection.meta = validate_restored_session_header(identity, inspection.meta)
            return inspection, interrupted_turn_closers(inspection.events)
        except SessionFormatUnsupportedError:
            raise
        except Exception as error:
            raise SessionPersistenceCorruptionError(identity, error) from error

    async def _load_unshared(self, identity):
        live = self._live_session(identity)
        if live is not None:
            events = list(live.events)
            if self._live_writes is not None:
                await self._live_writes.flush(live)
            if interrupted_turn_closers(events):
                raise ValueError('cannot load session while its live turn is open')
            return SessionInspection(live.header, events)
        stored = await self.store.load_stored(identity)
        inspection, closers = self._validate_cold(stored, identity)
        if 'tornMarker' in stored or closers:
            await self.store.commit_repair(stored['meta'], stored.get('tornMarker'), closers)
            inspection.events.extend(closers)
        return inspection

    async def inspect(self, identity, signal=None):
        return await self.prepared().inspect(identity, signal)

    async def load(self, identity):
        return await self.prepared().load(identity)

    async def read_from(self, identity, sequence, signal=None):
        if type(sequence) is not int or not 0 <= sequence <= 9007199254740991:
            from dsh.cordis.utils import js_to_string
            raise TypeError('readFrom fromSeq must be a non-negative safe integer, got ' + js_to_string(sequence))
        await self.prepared()._retired(identity, signal)
        async with self.storage_lock(identity):
            stored = await self.store.load_stored_from(identity, sequence, signal)
            if stored is None:
                raise SessionPersistenceNotFoundError(identity)
            if any(needs_legacy_prefix(event) for event in stored['events']):
                whole = await self.read_stored(identity)
                whole.events = [event for event in whole.events if event['seq'] >= sequence]
                return whole
            return validate_inspection(SessionInspection(header_from_stored(stored['meta']), stored['events']), identity)

    async def list(self, signal=None):
        return [header_from_stored(value) for value in await self.store.list(signal)]

    async def list_snapshots(self, signal=None):
        return [SessionPersistenceSnapshot(header_from_stored(value['header']), value['revision'])
                for value in await self.store.list_snapshots(signal)]

    async def close(self):
        await self.store.close()


class SqliteSessionPersistencePlugin(Plugin):
    id = 'session-persistence-sqlite'
    name = '@deepseek-ai/dsh-session-persistence-sqlite'
    inject = ['sessions']
    Config = Schema.object({
        'path': Schema.string().required(),
        'journalMode': Schema.union(['wal', 'delete', 'truncate', 'persist']).default('wal'),
        'busyTimeoutMs': Schema.number().step(1).min(0).max(2147483647).default(5000),
        'preparedSessionCacheSize': Schema.number().step(1).min(1).default(5),
        'writeBatchMaxDelayMs': Schema.number().step(1).min(1).max(2147483647).default(200),
    })

    async def apply(self, ctx):
        configuration = self.config
        persistence = SqliteSessionPersistence(configuration['path'], ctx=ctx,
            journal_mode=configuration.get('journalMode', 'wal'), busy_timeout_ms=configuration.get('busyTimeoutMs', 5000))
        await persistence.store.validate_path()
        persistence.prepared_cache_size = configuration.get('preparedSessionCacheSize', 5)
        persistence.prepared()
        from dsh.session.live_persistence import LivePersistence
        persistence._live_writes = LivePersistence(persistence, ctx, configuration.get('writeBatchMaxDelayMs', 200))
        ctx.set_service('session_persistence', persistence)
        ctx.set_service('sessionPersistence', persistence)
        persistence._live_writes.mount()
