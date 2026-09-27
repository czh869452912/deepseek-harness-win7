"""Shared public storage cursor and lazy creation, independent of physical backend."""
from dsh.core.session import SessionHeader, SESSION_FORMAT_VERSION, KNOWN_SESSION_EVENT_TYPES
from dsh.core.session.json import snapshot_json_value, UNDEFINED
from dsh.core.session.types import assert_message_event_shape
from dsh.session.persistence import SessionFormatUnsupportedError


def assert_supported_events(events):
    # Upstream deliberately permits unknown types on writes: refusing a future
    # plugin event here would stall the live durability queue. Reads fail closed.
    for event in events:
        kind = event.get('type')
        if kind in ('request/header-delta', 'mode/set'):
            raise ValueError('unsupported legacy ' + kind)
        if kind == 'request/header' and isinstance(event.get('data'), dict) and event['data'].get('reason') == 'fallback':
            raise ValueError('unsupported legacy request/header reason "fallback"')


def validate_stored(inspection, sid, location):
    if inspection.meta.id != sid:
        raise ValueError('requested id "{}" does not match header id "{}"'.format(sid, inspection.meta.id))
    if type(inspection.meta.version) is not int or inspection.meta.version != SESSION_FORMAT_VERSION:
        raise SessionFormatUnsupportedError('session "{}" uses log format v{}; upgrade the harness (raw log: {})'.format(sid, inspection.meta.version, location))
    assert_supported_events(inspection.events)
    for event in inspection.events:
        assert_message_event_shape(event, 'session event at seq {}'.format(event.get('seq')))
        if event.get('type') not in KNOWN_SESSION_EVENT_TYPES:
            raise SessionFormatUnsupportedError('session "{}" contains unsupported event type "{}"; upgrade the harness (raw log: {})'.format(sid, event.get('type'), location))
    return inspection


class PersistenceCoordinator:
    def __init__(self, backend):
        self.backend = backend
        self.states = {}

    def _writable(self, sid):
        if self.backend._prepared is not None:
            self.backend._prepared.assert_writable(sid)

    def adopted(self, inspection):
        self.states[inspection.meta.id] = dict(meta=inspection.meta, cursor=len(inspection.events), materialized=True)

    async def create(self, meta):
        raw = snapshot_json_value(meta.to_dict(), UNDEFINED)
        if raw is UNDEFINED:
            raise TypeError('session metadata must be losslessly JSON-serializable')
        value = raw.get('createdAt')
        if type(value) is not int or not 0 <= value <= 9007199254740991:
            raise TypeError('session metadata createdAt must be a non-negative safe integer')
        meta = SessionHeader.from_dict(raw)
        async with self.backend.storage_lock(meta.id):
            self._writable(meta.id)
            prepared = self.backend._prepared
            if meta.id in self.states or (prepared is not None and meta.id in prepared.pool.entries):
                raise ValueError('session already exists in this backend: ' + meta.id)
            try:
                await self.backend.read_stored(meta.id)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('session already has a persisted log: ' + meta.id)
            self.states[meta.id] = dict(meta=meta, cursor=0, materialized=False)

    async def append(self, sid, events):
        events = snapshot_json_value(events, UNDEFINED)
        if events is UNDEFINED or not isinstance(events, list):
            raise TypeError('session event batch is not losslessly JSON-serializable')
        assert_supported_events(events)
        if not events:
            return
        self._writable(sid)
        async with self.backend.storage_lock(sid):
            self._writable(sid)
            state = self.states.get(sid)
            if state is None:
                # Use the same validation/revision/repair boundary as restore.
                # Public load would deadlock on the storage lock held here.
                prepared = self.backend.prepared()
                while True:
                    source = prepared.pool.take_ready(sid)
                    if source is None:
                        source = await prepared._source(sid)
                    if await prepared._commit_locked(sid, source) is not None:
                        break
                state = self.states[sid]
            for index, event in enumerate(events):
                if type(event.get('seq')) is not int or event['seq'] != state['cursor'] + index:
                    raise ValueError('append seq mismatch for "{}": expected {} at index {}, got {}'.format(sid, state['cursor'] + index, index, event.get('seq')))
            await self.backend.append_batch(state['meta'], events, state['materialized'])
            state['materialized'] = True
            state['cursor'] += len(events)
            if self.backend._prepared is not None:
                self.backend._prepared.changed(sid)

    async def ensure_materialized(self, session):
        if self.backend._live_writes is None:
            raise ValueError('session is not registered for live persistence')
        await self.backend._live_writes.flush(session)
        async with self.backend.storage_lock(session.id):
            state = self.states[session.id]
            if not state['materialized']:
                await self.backend._create(state['meta'])
                state['materialized'] = True
                if self.backend._prepared is not None:
                    self.backend._prepared.changed(session.id)

    async def read_from(self, sid, from_seq, signal=None):
        from dsh.session.preparations import observe_queued_abort, throw_aborted
        from dsh.session.persistence import SessionInspection
        if type(from_seq) is not int or not 0 <= from_seq <= 9007199254740991:
            raise TypeError('readFrom fromSeq must be a non-negative safe integer')
        await self.backend.prepared()._retired(sid, signal)
        async def read():
            async with self.backend.storage_lock(sid):
                throw_aborted(signal)
                inspection = await self.backend.read_stored(sid)
                throw_aborted(signal)
                return SessionInspection(inspection.meta, [event for event in inspection.events if event['seq'] >= from_seq])
        awaitable = read()
        return await observe_queued_abort(awaitable, signal)
