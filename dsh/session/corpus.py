import asyncio
import copy

from dsh.session.preparations import throw_aborted


def not_found(session_id):
    from dsh.session.session_query import SessionQueryError
    return SessionQueryError('session "' + session_id + '" not found', 'SESSION_QUERY_SESSION_NOT_FOUND')


def assert_headers_compatible(first, second):
    from dsh.session.session_query import SessionQueryError
    keys = ('version', 'id', 'createdAt', 'cwd', 'parentSession', 'seedLength')
    if (any(getattr(first, key) != getattr(second, key) for key in keys)
            or (first.delegationDepth or 0) != (second.delegationDepth or 0)):
        raise SessionQueryError('session source headers conflict for session "' + first.id + '"',
                                'SESSION_QUERY_SOURCE_CONFLICT')


async def list_persisted(persistence, signal):
    from dsh.session.observation import error_message, failure_value
    from dsh.session.session_query import SessionQueryError
    try:
        return await persistence.list(signal)
    except Exception as error:
        throw_aborted(signal)
        failure = failure_value(error)
        raise SessionQueryError('session persistence listing failed: ' + error_message(failure),
                                'SESSION_QUERY_PERSISTENCE_FAILED', failure) from error


async def inspect_persisted(persistence, session_id, signal):
    from dsh.session.observation import error_message, failure_value
    from dsh.session.persistence import SessionPersistenceCorruptionError
    from dsh.session.session_query import SessionQueryError
    try:
        return await persistence.inspect(session_id, signal)
    except Exception as error:
        throw_aborted(signal)
        failure = failure_value(error)
        corrupt = isinstance(error, SessionPersistenceCorruptionError) or (
            isinstance(failure, BaseException) and getattr(failure, 'name', '') == 'SessionPersistenceCorruptionError')
        message = ('stored session "' + session_id + '" is corrupt: ' if corrupt
                   else 'failed to inspect session "' + session_id + '": ') + error_message(failure)
        code = 'SESSION_QUERY_CORRUPT_SESSION' if corrupt else 'SESSION_QUERY_PERSISTENCE_FAILED'
        raise SessionQueryError(message, code, failure) from error


def inspection_source(inspection):
    return {'header': inspection['meta'], 'events': inspection['events']} if isinstance(inspection, dict) else {
        'header': inspection.meta, 'events': inspection.events}


def live_source(session):
    return {'header': session.header, 'events': session.events}


class SessionCorpus:
    def __init__(self, ctx, persisted_inspect_concurrency=4):
        self.ctx = ctx
        self.persisted_inspect_concurrency = persisted_inspect_concurrency

    async def load(self, session_id, signal=None):
        throw_aborted(signal)
        live = self.ctx.get('sessions').get(session_id)
        if live is not None:
            result = copy.deepcopy(live_source(live))
            throw_aborted(signal)
            return result
        persistence = self.ctx.get('sessionPersistence')
        if persistence is None:
            raise not_found(session_id)
        listed = next((header for header in await list_persisted(persistence, signal) if header.id == session_id), None)
        throw_aborted(signal)
        if listed is None:
            raise not_found(session_id)
        loaded = inspection_source(await inspect_persisted(persistence, session_id, signal))
        throw_aborted(signal)
        attached = self.ctx.get('sessions').get(session_id)
        if attached is not None:
            result = copy.deepcopy(live_source(attached))
        else:
            assert_headers_compatible(loaded['header'], listed)
            result = copy.deepcopy(loaded)
        throw_aborted(signal)
        return result

    async def project_many(self, session_ids, project, signal=None):
        ids = list(dict.fromkeys(session_ids))
        throw_aborted(signal)
        resolved, unresolved = {}, []
        def project_source(session_id, source):
            try:
                throw_aborted(signal)
                value = project(source)
                throw_aborted(signal)
                return {'sessionId': session_id, 'status': 'fulfilled', 'value': value}
            except Exception as error:
                throw_aborted(signal)
                from dsh.session.observation import failure_value
                return {'sessionId': session_id, 'status': 'rejected', 'reason': failure_value(error)}
        for session_id in ids:
            live = self.ctx.get('sessions').get(session_id)
            if live is None:
                unresolved.append(session_id)
            else:
                resolved[session_id] = project_source(session_id, live_source(live))
        if not unresolved:
            return [resolved[session_id] for session_id in ids]
        persistence = self.ctx.get('sessionPersistence')
        if persistence is None:
            for session_id in unresolved:
                resolved[session_id] = {'sessionId': session_id, 'status': 'rejected', 'reason': not_found(session_id)}
            return [resolved[session_id] for session_id in ids]
        try:
            persisted = await list_persisted(persistence, signal)
            throw_aborted(signal)
        except Exception as error:
            throw_aborted(signal)
            for session_id in unresolved:
                resolved[session_id] = {'sessionId': session_id, 'status': 'rejected', 'reason': error}
            return [resolved[session_id] for session_id in ids]
        by_id = {header.id: header for header in persisted}
        async def resolve_persisted(session_id):
            listed = by_id.get(session_id)
            if listed is None:
                attached = self.ctx.get('sessions').get(session_id)
                resolved[session_id] = (project_source(session_id, live_source(attached)) if attached is not None
                    else {'sessionId': session_id, 'status': 'rejected', 'reason': not_found(session_id)})
                return
            try:
                throw_aborted(signal)
                loaded = inspection_source(await inspect_persisted(persistence, session_id, signal))
                throw_aborted(signal)
                attached = self.ctx.get('sessions').get(session_id)
                if attached is not None:
                    resolved[session_id] = project_source(session_id, live_source(attached))
                    return
                assert_headers_compatible(loaded['header'], listed)
                resolved[session_id] = project_source(session_id, loaded)
            except Exception as error:
                throw_aborted(signal)
                resolved[session_id] = {'sessionId': session_id, 'status': 'rejected', 'reason': error}
        cursor = 0
        async def worker():
            nonlocal cursor
            while True:
                throw_aborted(signal)
                if cursor >= len(unresolved):
                    return
                index = cursor
                cursor += 1
                await resolve_persisted(unresolved[index])
        settlements = await asyncio.gather(*(worker() for _ in range(
            min(self.persisted_inspect_concurrency, len(unresolved)))), return_exceptions=True)
        throw_aborted(signal)
        for settlement in settlements:
            if isinstance(settlement, BaseException):
                raise settlement
        return [resolved[session_id] for session_id in ids]
