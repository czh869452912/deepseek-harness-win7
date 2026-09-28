"""Live-preferred point observations with independently retained cold leases."""
from dsh.core.session.json import deep_freeze
from dsh.session.persistence import SessionPersistenceCorruptionError
from dsh.session.session_query import SessionQueryError


class SessionObservation:
    def __init__(self, state):
        self._state = state
        self._disposed = False

    def __getattr__(self, name):
        return self._state['view'][name]

    def retain(self):
        if self._disposed:
            raise RuntimeError('session observation is disposed')
        self._state['references'] += 1
        return SessionObservation(self._state)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._state['references'] -= 1
        if not self._state['references']:
            self._state['release']()


def check_abort(signal):
    if signal is not None and signal.aborted:
        raise SessionQueryError('session observation was aborted', 'SESSION_QUERY_ABORTED', signal.reason)


class SessionObservationReader:
    def __init__(self, ctx):
        self.ctx = ctx

    def cut(self, source, header, events, release, projections=None, revision=None):
        events = tuple(deep_freeze(event) for event in events)
        view = dict(source=source, header=header, events=events,
                    cursor=events[-1]['seq'] if events else -1,
                    projections=projections, revision=revision)
        return SessionObservation(dict(view=view, references=1, release=release))

    def live(self, session, mode):
        registry = self.ctx.get('sessionProjections')
        events = tuple(session.events)
        projections = registry.snapshot(session) if registry is not None and mode != 'none' else None
        return self.cut('live', session.header, events, lambda: None, projections)

    async def read(self, session_id, options=None):
        options = options or {}
        signal, mode = options.get('signal'), options.get('projectionMode', 'all')
        while True:
            check_abort(signal)
            sessions = self.ctx.get('sessions')
            live = sessions.get(session_id)
            if live is not None:
                return self.live(live, mode)
            persistence = self.ctx.get('sessionPersistence')
            if persistence is None:
                raise SessionQueryError('session not found: ' + session_id, 'SESSION_QUERY_SESSION_NOT_FOUND')
            try:
                borrowed = await persistence.borrowSession(session_id, signal)
            except Exception as error:
                check_abort(signal)
                code = ('SESSION_QUERY_SESSION_NOT_FOUND' if isinstance(error, FileNotFoundError) else
                        'SESSION_QUERY_CORRUPT_SESSION' if isinstance(error, SessionPersistenceCorruptionError) else
                        'SESSION_QUERY_PERSISTENCE_FAILED')
                raise SessionQueryError('failed to observe session: ' + session_id, code, error) from error
            try:
                check_abort(signal)
                if borrowed.inspection.meta.id != session_id:
                    raise SessionQueryError('session source identity conflict', 'SESSION_QUERY_SOURCE_CONFLICT')
                live = sessions.get(session_id)
                if live is not None:
                    observation = self.live(live, mode)
                    borrowed.dispose()
                    return observation
                if borrowed.source == 'live':
                    borrowed.dispose()
                    continue
                projections = None
                registry = self.ctx.get('sessionProjections')
                if mode != 'none' and registry is not None:
                    cache = self.ctx.get('sessionProjectionCache')
                    try:
                        projections = (cache.hydratePrepared(borrowed.preparedSession, borrowed.inspection.meta,
                                                            borrowed.inspection.events) if cache is not None else
                                       registry.hydrate(borrowed.preparedSession, {}, borrowed.inspection.events, 0))
                    except Exception as error:
                        raise SessionQueryError('failed to project session: ' + session_id,
                                                'SESSION_QUERY_CORRUPT_SESSION', error) from error
                return self.cut('prepared', borrowed.inspection.meta, borrowed.inspection.events,
                                borrowed.dispose, projections, borrowed.revision)
            except BaseException:
                borrowed.dispose()
                raise
