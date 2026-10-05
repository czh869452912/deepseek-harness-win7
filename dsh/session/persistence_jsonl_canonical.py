from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.session.persistence import SessionPersistence, SessionInspection, SessionPersistenceSnapshot, SessionLocation, SessionFormatUnsupportedError
from dsh.session.sqlite_logical import header_from_stored, validate_inspection, SessionPersistenceNotFoundError, SessionPersistenceCorruptionError
from dsh.session.repair import interrupted_turn_closers
from dsh.session.jsonl_store import JsonlStore
from dsh.core.session.types import validate_restored_session_header


class JsonlSessionPersistence(SessionPersistence):
    supports_raw_artifacts = True
    name = 'session-persistence-jsonl'

    def __init__(self, root, compression='zstd', pack_chunks=True, ctx=None):
        super().__init__(ctx)
        self.store = JsonlStore(root, compression, pack_chunks)
        self.root = self.store.root
        self.compression = compression
        self.pack_chunks = pack_chunks
        self._live_writes = None

    def locate(self, metadata):
        return SessionLocation('jsonl', self.store.locate(metadata.to_dict()))

    async def create(self, metadata):
        await self.storage().create(metadata)

    async def append(self, identity, events):
        await self.storage().append(identity, events)

    async def append_batch(self, metadata, events, materialized):
        await self.store.append_batch(metadata.to_dict(), events, materialized)

    async def _create(self, metadata):
        await self.store.materialize_header(metadata.to_dict())

    async def ensure_materialized(self, session):
        await self.storage().ensure_materialized(session)

    ensureMaterialized = ensure_materialized

    async def read_stored(self, identity, signal=None):
        stored = await self.store.load_stored(identity, signal)
        if stored is None:
            raise SessionPersistenceNotFoundError(identity)
        inspection = SessionInspection(header_from_stored(stored['meta']), stored['events'])
        return validate_inspection(inspection, identity)

    async def load_stored(self, identity):
        stored = await self.store.load_stored(identity)
        if stored is None:
            return None
        result = dict(meta=header_from_stored(stored['meta']), events=stored['events'], revision=stored['revision'])
        if 'tornMarker' in stored:
            result['tornMarker'] = stored['tornMarker']
        return result

    loadStored = load_stored

    async def stored_revision(self, identity):
        return await self.store.read_revision(identity)

    def _live_session(self, identity):
        sessions = self.ctx.get('sessions') if self.ctx is not None else None
        return sessions.get(identity) if sessions is not None else None

    async def repair_tail(self, identity):
        stored = await self.store.load_stored(identity)
        if stored is not None and 'tornMarker' in stored:
            await self.store.commit_repair(stored['meta'], stored['tornMarker'], [])

    def _validate_cold(self, stored, identity):
        if stored is None:
            raise SessionPersistenceNotFoundError(identity)
        try:
            inspection = validate_inspection(SessionInspection(header_from_stored(stored['meta']), stored['events']), identity)
            inspection.meta = validate_restored_session_header(identity, inspection.meta)
            return inspection, interrupted_turn_closers(inspection.events)
        except SessionFormatUnsupportedError:
            raise
        except Exception as error:
            raise SessionPersistenceCorruptionError(identity, error) from error

    async def _inspect_unshared(self, identity):
        live = self._live_session(identity)
        if live is not None:
            return SessionInspection(live.header, list(live.events))
        stored = await self.store.load_stored(identity)
        inspection, closers = self._validate_cold(stored, identity)
        inspection.events.extend(closers)
        return inspection

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
        from dsh.session.coordinator import safe_integer
        from dsh.session.preparations import observe_queued_abort, throw_aborted
        if not safe_integer(sequence) or sequence < 0:
            from dsh.cordis.utils import js_to_string
            raise TypeError('readFrom fromSeq must be a non-negative safe integer, got ' + js_to_string(sequence))
        sequence = int(sequence)
        await self.prepared()._retired(identity, signal)
        started = [False]
        async def read():
            async with self.storage_lock(identity):
                started[0] = True
                throw_aborted(signal)
                stored = await self.read_stored(identity, signal)
                throw_aborted(signal)
                stored.events = [event for event in stored.events if event['seq'] >= sequence]
                return stored
        return await observe_queued_abort(read(), signal, lambda: started[0])

    async def list(self, signal=None):
        return [header_from_stored(value) for value in await self.store.list(signal)]

    async def list_snapshots(self, signal=None):
        return [SessionPersistenceSnapshot(header_from_stored(value['header']), value['revision'])
            for value in await self.store.list_snapshots(signal)]

    async def read_raw(self, identity, signal=None):
        return await self.store.read_raw(identity, signal)

    async def on_session_flush(self, session=None):
        if self._live_writes is not None:
            await self._live_writes.flush(session)

    async def close(self):
        await self.store.close()


class JsonlSessionPersistencePlugin(Plugin):
    id = 'session-persistence-jsonl'
    name = '@deepseek-ai/dsh-session-persistence-jsonl'
    inject = ['sessions']
    Config = Schema.object({
        'root': Schema.string().required(),
        'packChunks': Schema.boolean().default(True),
        'compression': Schema.union(['zstd', 'none']).default('zstd'),
        'preparedSessionCacheSize': Schema.number().step(1).min(1).default(5),
        'writeBatchMaxDelayMs': Schema.number().step(1).min(1).max(2147483647).default(200),
    })

    async def apply(self, ctx):
        configuration = self.config
        persistence = JsonlSessionPersistence(configuration['root'], configuration.get('compression', 'zstd'),
            configuration.get('packChunks', True), ctx)
        persistence.prepared_cache_size = configuration.get('preparedSessionCacheSize', 5)
        persistence.prepared()
        from dsh.session.live_persistence import LivePersistence
        persistence._live_writes = LivePersistence(persistence, ctx, configuration.get('writeBatchMaxDelayMs', 200))
        ctx.set_service('session_persistence', persistence)
        ctx.set_service('sessionPersistence', persistence)
        persistence._live_writes.mount()
