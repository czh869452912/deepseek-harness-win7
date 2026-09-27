"""Shared cold sources, pinned leases and exclusive Session reservations."""
import asyncio
import inspect
from collections import OrderedDict
from types import SimpleNamespace


def throw_aborted(signal):
    if signal is not None and signal.aborted:
        reason = signal.reason
        if isinstance(reason, BaseException):
            raise reason
        error = RuntimeError('operation aborted')
        error.reason = reason
        raise error


async def observe_queued_abort(operation, signal=None, started=lambda: False):
    operation = asyncio.ensure_future(operation)
    if signal is None:
        return await asyncio.shield(operation)
    view = asyncio.get_event_loop().create_future()
    def aborted(*args):
        if started() or view.done():
            return
        try:
            throw_aborted(signal)
        except BaseException as error:
            view.set_exception(error)
    def settled(job):
        if job.cancelled():
            error = asyncio.CancelledError()
        else:
            error = job.exception()
        if view.done():
            return
        if error is not None:
            view.set_exception(error)
        else:
            view.set_result(job.result())
    remove = signal.add_listener('abort', aborted)
    operation.add_done_callback(settled)
    try:
        return await view
    finally:
        remove()


class PreparationLease:
    def __init__(self, source, release):
        self.source = source
        self._release = release
    def dispose(self):
        if self._release is not None:
            release, self._release = self._release, None
            release()


class SessionPreparations:
    def __init__(self, capacity=5):
        if type(capacity) is not int or capacity < 1:
            raise TypeError('preparedSessionCacheSize must be a positive integer')
        self.capacity = capacity
        self.entries = OrderedDict()
        self.jobs = set()

    def _start(self, coroutine):
        job = asyncio.ensure_future(coroutine)
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)
        return job

    def has(self, sid):
        return sid in self.entries

    def _entry(self, sid, load):
        if sid in self.entries:
            return self.entries[sid]
        entry = SimpleNamespace(id=sid, phase='loading', source=None, reservation=None,
                                settled=None, pins=0, result=asyncio.get_event_loop().create_future())
        self.entries[sid] = entry
        try:
            loading = load()
        except BaseException as error:
            self._remove(entry)
            entry.result.set_exception(error)
            return entry
        async def finish():
            try:
                source = await loading if inspect.isawaitable(loading) else loading
            except BaseException as error:
                self._remove(entry)
                entry.result.set_exception(error)
            else:
                if self.entries.get(sid) is entry:
                    entry.source = source
                    self._ready(entry)
                entry.result.set_result(source)
        self._start(finish())
        # A cancelled sole observer must not leave an unobserved loader failure.
        entry.result.add_done_callback(lambda job: None if job.cancelled() else job.exception())
        return entry

    async def inspect(self, sid, load, signal=None):
        entry = self._entry(sid, load)
        loaded = await observe_queued_abort(entry.result, signal)
        if self.entries.get(sid) is entry and entry.phase == 'ready':
            self._touch(entry)
        return entry.source if entry.source is not None else loaded

    async def borrow(self, sid, load, signal=None):
        entry = self._entry(sid, load)
        pinned = self.entries.get(sid) is entry
        if pinned:
            entry.pins += 1
        def release():
            if pinned and self.entries.get(sid) is entry:
                entry.pins -= 1
                if entry.phase == 'ready':
                    self._touch(entry)
        try:
            loaded = await observe_queued_abort(entry.result, signal)
        except BaseException:
            release()
            raise
        if self.entries.get(sid) is entry and entry.phase == 'ready':
            self._touch(entry)
        return PreparationLease(entry.source if entry.source is not None else loaded, release)

    async def reserve(self, sid, load, commit, signal=None):
        entry = self._entry(sid, load)
        await observe_queued_abort(entry.result, signal)
        while self.entries.get(sid) is entry and entry.phase != 'ready':
            await observe_queued_abort(entry.settled, signal)
        if self.entries.get(sid) is not entry:
            return None
        entry.phase = 'committing'
        entry.settled = asyncio.get_event_loop().create_future()
        # Once committing, durable work cannot be cancelled by an observer.
        async def finish():
            try:
                result = commit(entry.source)
                committed = await result if inspect.isawaitable(result) else result
            except BaseException:
                self._remove(entry)
                raise
            if committed is None:
                self._remove(entry)
                return None
            entry.source = committed['source']
            try:
                throw_aborted(signal)
            except BaseException:
                self._ready(entry)
                raise
            if self.entries.get(sid) is not entry:
                return None
            reservation = SimpleNamespace(entry=entry, source=entry.source, state=committed['state'])
            entry.phase = 'reserved'
            entry.reservation = reservation
            return reservation
        job = self._start(finish())
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            def abandoned(task):
                if not task.cancelled() and task.exception() is None and task.result() is not None:
                    self.release(task.result(), True)
            job.add_done_callback(abandoned)
            raise

    def reservation_for(self, session):
        entry = self.entries.get(session.id)
        if entry is None:
            return None
        if entry.phase == 'reserved' and entry.source.session is session:
            return entry.reservation
        raise ValueError('cannot publish session "{}": persisted state already owns this identity'.format(session.id))

    def attach(self, reservation):
        entry = reservation.entry
        if self.entries.get(entry.id) is not entry or entry.reservation is not reservation:
            raise ValueError('session preparation is no longer reserved')
        self._remove(entry)

    def discard(self, reservation):
        if self.entries.get(reservation.entry.id) is reservation.entry and reservation.entry.reservation is reservation:
            self._remove(reservation.entry)

    def release(self, reservation, reusable):
        entry = reservation.entry
        if self.entries.get(entry.id) is not entry or entry.reservation is not reservation or entry.phase != 'reserved':
            return
        if not reusable:
            self._remove(entry)
        else:
            entry.reservation = None
            self._ready(entry)

    def invalidate(self, sid):
        if sid in self.entries:
            self._remove(self.entries[sid])

    def discard_ready(self, sid, expected):
        entry = self.entries.get(sid)
        if entry is None or entry.source is not expected:
            return 'missing'
        if entry.phase != 'ready':
            return 'retained'
        self._remove(entry)
        return 'discarded'

    def assert_writable(self, sid):
        entry = self.entries.get(sid)
        if entry is not None and entry.phase in ('committing', 'reserved'):
            raise ValueError('cannot append session "{}" while its persisted preparation is reserved'.format(sid))

    def take_ready(self, sid):
        entry = self.entries.get(sid)
        if entry is None or entry.phase != 'ready':
            return None
        self._remove(entry)
        return entry.source

    def _settle(self, entry):
        if entry.settled is not None:
            entry.settled.set_result(None)
            entry.settled = None

    def _remove(self, entry):
        if self.entries.get(entry.id) is entry:
            del self.entries[entry.id]
            self._settle(entry)

    def _ready(self, entry):
        if self.entries.get(entry.id) is entry:
            entry.phase = 'ready'
            self._settle(entry)
            self._touch(entry)

    def _touch(self, entry):
        self.entries.move_to_end(entry.id)
        if sum(e.phase == 'ready' for e in self.entries.values()) > self.capacity:
            for sid, candidate in self.entries.items():
                if candidate.phase == 'ready' and not candidate.pins:
                    del self.entries[sid]
                    break
