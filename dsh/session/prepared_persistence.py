"""Cold inspection sharing and reserved restore identities for both backends."""
import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from dsh.core.session import Session
from dsh.core.session.preparation import SessionPreparation
from dsh.session.preparations import SessionPreparations, throw_aborted, observe_queued_abort


class PreparedPersistence:
    def __init__(self, backend, capacity=5):
        self.closed = False
        self.backend = backend
        self.pool = SessionPreparations(capacity)

    async def _retired(self, sid, signal=None):
        if self.closed:
            raise RuntimeError("session preparation provider is closed")
        live = self.backend._live_writes
        job = live.retirements.get(sid) if live is not None else None
        if job is not None:
            await observe_queued_abort(job, signal)
        throw_aborted(signal)

    def _live(self, sid):
        return self.backend._live_session(sid)

    async def revision(self, sid):
        reader = getattr(self.backend, 'stored_revision', None)
        if reader is not None:
            return await reader(sid)
        stored = await self.backend.read_stored(sid)
        raw = json.dumps([stored.meta.to_dict(), stored.events], sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    async def _source(self, sid):
        while True:
            before = await self.revision(sid)
            inspection = await self.backend._inspect_unshared(sid)
            after = await self.revision(sid)
            if before == after:
                session = Session.from_restore(session_id=sid, seed=copy.deepcopy(inspection.events),
                                               header=inspection.meta, ctx=self.backend.ctx)
                return SimpleNamespace(session=session, inspection=inspection, revision=after,
                                       length=len(session.events))

    async def inspect(self, sid, signal=None):
        while True:
            await self._retired(sid, signal)
            if self._live(sid) is not None:
                return await self.backend._inspect_unshared(sid)
            source = await self.pool.inspect(sid, lambda: self._source(sid), signal)
            if self.closed:
                raise RuntimeError("session preparation provider is closed")
            if source.revision == await self.revision(sid):
                return copy.deepcopy(source.inspection)
            if self.pool.discard_ready(sid, source) == 'retained':
                return copy.deepcopy(source.inspection)

    async def borrow(self, sid, signal=None):
        from dsh.session.persistence import SessionInspection
        def live_view(live):
            return SimpleNamespace(source='live', inspection=SessionInspection(
                live.header, tuple(live.events)), dispose=lambda: None)
        while True:
            await self._retired(sid, signal)
            live = self._live(sid)
            if live is not None:
                return live_view(live)
            lease = await self.pool.borrow(sid, lambda: self._source(sid), signal)
            try:
                throw_aborted(signal)
                if self.closed:
                    raise RuntimeError("session preparation provider is closed")
                live = self._live(sid)
                if live is not None:
                    lease.dispose()
                    return live_view(live)
                source = lease.source
                async with self.backend.storage_lock(sid):
                    throw_aborted(signal)
                    current = source.revision == await self.revision(sid)
                live = self._live(sid)
                if live is not None:
                    lease.dispose()
                    return live_view(live)
                if current or self.pool.discard_ready(sid, source) == 'retained':
                    return SimpleNamespace(source='prepared', inspection=source.inspection,
                                           preparedSession=source.session, revision=source.revision,
                                           dispose=lease.dispose)
            except BaseException:
                lease.dispose()
                throw_aborted(signal)
                live = self._live(sid)
                if live is not None:
                    return live_view(live)
                raise
            lease.dispose()

    async def _commit(self, sid, source, signal=None):
        async with self.backend.storage_lock(sid):
            throw_aborted(signal)
            return await self._commit_locked(sid, source)

    async def _commit_locked(self, sid, source):
        if self._live(sid) is not None:
            raise ValueError('cannot prepare session while it is live')
        if source.revision != await self.revision(sid):
            return None
        # The raw load owns crash repair; public append stays reserved.
        await self.backend._load_unshared(sid)
        if source.revision != await self.revision(sid):
            return None
        self.backend.storage().adopted(source.inspection)
        return {'source': source, 'state': {'owner': None}}

    async def load(self, sid):
        while True:
            await self._retired(sid)
            if self._live(sid) is not None:
                return await self.backend._load_unshared(sid)
            reservation = await self.pool.reserve(sid, lambda: self._source(sid),
                lambda source: self._commit(sid, source))
            if reservation is not None:
                result = copy.deepcopy(reservation.source.inspection)
                self.pool.discard(reservation)
                return result

    async def prepare(self, sid, signal=None):
        while True:
            await self._retired(sid, signal)
            if self._live(sid) is not None:
                raise ValueError('cannot prepare session while it is live')
            reservation = await self.pool.reserve(sid, lambda: self._source(sid),
                lambda source: self._commit(sid, source, signal), signal)
            if reservation is None:
                continue
            if self.closed:
                self.pool.release(reservation, False)
                raise RuntimeError("session preparation provider is closed")
            if self._live(sid) is not None:
                self.pool.release(reservation, False)
                raise ValueError('cannot prepare session while it is live')
            try:
                if reservation.source.session is None:
                    view = reservation.source.inspection
                    reservation.source.session = Session.from_restore(session_id=sid,
                        seed=view.events, header=view.meta, ctx=self.backend.ctx)
                    reservation.source.length = len(reservation.source.session.events)
            except BaseException:
                self.pool.release(reservation, False)
                raise
            def release(reservation=reservation):
                reusable = reservation.state['owner'] is None and len(reservation.source.session.events) == reservation.source.length
                self.pool.release(reservation, reusable)
            return SessionPreparation.create(reservation.source.session, {'release': release})

    async def drain(self):
        self.closed = True
        for sid in list(self.pool.entries):
            self.pool.invalidate(sid)
        while self.pool.jobs:
            await asyncio.gather(*list(self.pool.jobs), return_exceptions=True)

    def attach(self, session):
        reservation = self.pool.reservation_for(session)
        if reservation is not None:
            reservation.state['owner'] = session
            self.pool.attach(reservation)

    def assert_writable(self, sid):
        self.pool.assert_writable(sid)

    def changed(self, sid):
        self.pool.invalidate(sid)
