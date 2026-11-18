"""Live-preferred observations, retained cold cuts, and lazy live snapshots."""
import copy
from collections import OrderedDict

from dsh.core.session.json import FrozenList
from dsh.session.cold_read import readColdSessionLog
from dsh.session.observation import check_abort, error_message, failure_value
from dsh.session.session_query import SessionQueryError
from dsh.session.storage_contract import field

SESSION_QUERY_DEFAULT_PREPARED_SESSION_CACHE_SIZE = 5


class CurrentSessionObservation:
    def __init__(self, view, retain, release):
        self._view, self._retain, self._release = view, retain, release
        self._disposed = False

    def __getattr__(self, key):
        if key not in self._view:
            raise AttributeError(key)
        value = self._view[key]
        return value() if key=='events' and callable(value) else value

    @property
    def projections(self):
        """An observation without projection work exposes an absent baseline."""
        return self._view.get('projections')

    def retain(self):
        if self._disposed:
            raise ValueError('session observation "%s" is disposed' % field(self._view['header'],'id'))
        return self._retain()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._release()


def not_found(session_id, cause=None):
    return SessionQueryError('session "%s" not found' % session_id,'SESSION_QUERY_SESSION_NOT_FOUND',cause)


def map_failure(session_id, error):
    error = failure_value(error)
    if isinstance(error,BaseException) and getattr(error,'name',None)=='SessionPersistenceNotFoundError':
        return not_found(session_id,error)
    if isinstance(error,BaseException) and getattr(error,'name',None)=='SessionPersistenceCorruptionError':
        return SessionQueryError('stored session "%s" is corrupt: %s' % (session_id,error),
                                 'SESSION_QUERY_CORRUPT_SESSION',error)
    return SessionQueryError('failed to observe session "%s": %s' % (session_id,error_message(error)),
                             'SESSION_QUERY_PERSISTENCE_FAILED',error)


class CurrentSessionObservationReader:
    def __init__(self, ctx, cache_capacity=SESSION_QUERY_DEFAULT_PREPARED_SESSION_CACHE_SIZE):
        self.ctx, self.cacheCapacity = ctx, cache_capacity
        self.cache = OrderedDict()

    async def read(self, session_id, options=None):
        options = options or {}
        signal,mode = options.get('signal'),options.get('projectionMode','all')
        sessions = self.ctx.get('sessions')
        while True:
            check_abort(signal)
            live = sessions.get(session_id)
            if live is not None:
                return self.live(live,mode)
            persistence = self.ctx.get('sessionPersistence')
            if persistence is None:
                raise not_found(session_id)
            snapshot = await self.statSource(persistence,session_id,signal)
            attached = sessions.get(session_id)
            if attached is not None:
                return self.live(attached,mode)
            entry = self.cachedEntry(persistence,session_id,field(snapshot,'revision'))
            if entry is None:
                loaded = await self.loadSource(persistence,session_id,signal)
                check_abort(signal)
                attached = sessions.get(session_id)
                if attached is not None:
                    return self.live(attached,mode)
                seed = loaded['events']
                try:
                    session = sessions.prepare(session_id,dict(seed=seed,meta=copy.deepcopy(loaded['header']),
                        inheritedEventCount=loaded['inheritedEventCount'],eventState=loaded['eventState']))
                except Exception as error:
                    if sessions.get(session_id) is not None:
                        continue
                    raise SessionQueryError('stored session "%s" is corrupt: %s' % (session_id,error_message(failure_value(error))),
                                             'SESSION_QUERY_CORRUPT_SESSION',failure_value(error)) from error
                entry = dict(persistence=persistence,revision=field(snapshot,'revision'),session=session,
                             events=FrozenList(seed),refs=0)
                self.store(session_id,entry)
            try:
                projections = None if mode=='none' else self.preparedProjections(entry)
            except Exception as error:
                raise SessionQueryError('failed to project session "%s": %s' % (session_id,error_message(failure_value(error))),
                                         'SESSION_QUERY_CORRUPT_SESSION',failure_value(error)) from error
            return self.preparedLease(session_id,entry,projections)

    async def statSource(self, persistence, session_id, signal):
        try:
            snapshot = await persistence.stat(session_id,None if signal is None else dict(signal=signal))
        except Exception as error:
            check_abort(signal)
            raise map_failure(session_id,error) from error
        check_abort(signal)
        if snapshot is None:
            raise not_found(session_id)
        header = field(snapshot,'header')
        if field(header,'id')!=session_id:
            raise SessionQueryError('session persistence returned "%s" for "%s"' % (field(header,'id'),session_id),
                                     'SESSION_QUERY_SOURCE_CONFLICT')
        return snapshot

    async def loadSource(self, persistence, session_id, signal):
        try:
            return await readColdSessionLog(persistence,session_id,signal)
        except Exception as error:
            check_abort(signal)
            raise map_failure(session_id,error) from error

    def cachedEntry(self, persistence, session_id, revision):
        entry = self.cache.get(session_id)
        if entry is None or entry['persistence'] is not persistence or entry['revision']!=revision:
            return None
        self.cache.move_to_end(session_id)
        return entry

    def store(self, session_id, entry):
        self.cache.pop(session_id,None)
        self.cache[session_id] = entry
        self.evictPastCapacity(entry)

    def evictPastCapacity(self, keep=None):
        for session_id,candidate in list(self.cache.items()):
            if len(self.cache)<=self.cacheCapacity:
                return
            if candidate is keep or candidate['refs']>0:
                continue
            self.cache.pop(session_id,None)

    def preparedLease(self, session_id, entry, projections):
        entry['refs'] += 1
        view = dict(source='prepared',header=entry['session'].header,
                    inheritedEventCount=entry['session'].inheritedEventCount,
                    events=entry['events'],cursor=entry['events'][-1]['seq'] if entry['events'] else -1,
                    revision=entry['revision'])
        if projections is not None:
            view['projections'] = projections
        def release():
            entry['refs'] -= 1
            if not entry['refs']:
                self.evictPastCapacity()
        return CurrentSessionObservation(view,lambda:self.preparedLease(session_id,entry,projections),release)

    def live(self, session, mode):
        cut,materialized = session.seq,[]
        def events():
            if not materialized:
                materialized.append(session.snapshotEvents(0,cut))
            return materialized[0]
        registry = self.ctx.get('sessionProjections')
        try:
            projections = None if mode=='none' or registry is None else registry.snapshot(session)
        except Exception as error:
            raise SessionQueryError('failed to project session "%s": %s' % (session.id,error_message(failure_value(error))),
                                    'SESSION_QUERY_CORRUPT_SESSION',failure_value(error)) from error
        view = dict(source='live',header=session.header,inheritedEventCount=session.inheritedEventCount,
                    events=events,cursor=cut-1 if cut else -1)
        if projections is not None:
            view['projections'] = projections
        def lease():
            return CurrentSessionObservation(view,lease,lambda:None)
        return lease()

    def preparedProjections(self, entry):
        registry = self.ctx.get('sessionProjections')
        if registry is None:
            return None
        cache = self.ctx.get('sessionProjectionCache')
        return (registry.hydrate(entry['session'],{},entry['events'],0) if cache is None else
                cache.hydratePrepared(entry['session'],entry['events']))
