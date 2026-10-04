import asyncio
import base64
import copy
from functools import cmp_to_key
import hashlib
import json
import math
import uuid

from dsh.cordis.json_text import stringify_json
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionHeader
from dsh.session.corpus import assert_headers_compatible, inspection_source
from dsh.session.icu_collation import locale_compare
from dsh.session.observation import error_message, failure_value
from dsh.session.query_requests import (
    MAX_PAGE_LIMIT, WHITESPACE, assert_binding_count, assert_predicate_count,
    build_event_where, build_session_where, make_snippet,
    normalize_event_request, normalize_session_request,
)
from dsh.session.query_schema import open_search_database
from dsh.session.session_query import (
    SessionQueryError, SessionQueryService, build_session_event_search_documents,
    quote_fts_data, sanitize_fts_text,
)


HEADER_COLUMNS = ('version', 'id', 'createdAt', 'cwd', 'parentSession', 'seedLength', 'delegationDepth', 'agentPreset')


def invalid_config(detail):
    return SessionQueryError('session-search SQLite config: ' + detail, 'SESSION_QUERY_INVALID_CONFIG')


def resolve_config(config):
    import re
    defaults = dict(openAt='startup', journalMode='wal', defaultLimit=20, maxLimit=100,
                    snippetChars=240, readWindowMax=50, persistedInspectConcurrency=4)
    resolved = dict(path=config.get('path'))
    resolved.update({name: config.get(name) if config.get(name) is not None else value
                     for name, value in defaults.items()})
    path = resolved['path']
    if not isinstance(path, str) or not re.sub('^' + WHITESPACE + '+|' + WHITESPACE + '+$', '', path):
        raise invalid_config('path must not be blank')
    if resolved['openAt'] not in ('startup', 'first-search', 'never'):
        raise invalid_config('openAt is not supported')
    for name in ('defaultLimit', 'maxLimit'):
        value = resolved[name]
        if not integer(value) or not 1 <= value <= MAX_PAGE_LIMIT:
            raise invalid_config(name + ' must be an integer between 1 and ' + str(MAX_PAGE_LIMIT))
    if not integer(resolved['snippetChars']) or resolved['snippetChars'] < 1:
        raise invalid_config('snippetChars must be a positive integer')
    if not integer(resolved['readWindowMax']) or resolved['readWindowMax'] < 0:
        raise invalid_config('readWindowMax must be a non-negative integer')
    if not integer(resolved['persistedInspectConcurrency']) or not 1 <= resolved['persistedInspectConcurrency'] <= 9007199254740991:
        raise invalid_config('persistedInspectConcurrency must be a positive safe integer')
    if resolved['defaultLimit'] > resolved['maxLimit']:
        raise invalid_config('defaultLimit must be less than or equal to maxLimit')
    if resolved['journalMode'] not in ('wal', 'delete', 'truncate', 'persist'):
        raise invalid_config('journalMode is not supported')
    return resolved


def integer(value):
    return type(value) is int or (type(value) is float and math.isfinite(value) and int(value) == value)


def check_abort(signal):
    if signal is not None and signal.aborted:
        raise SessionQueryError('session-search aborted', 'SESSION_QUERY_ABORTED')


def index_closed():
    return SessionQueryError('session-search SQLite index is closed', 'SESSION_QUERY_INDEX_FAILED')


async def wait_with_abort(operation, signal):
    if signal is None:
        return await asyncio.shield(operation)
    check_abort(signal)
    view = asyncio.get_event_loop().create_future()
    def aborted(*args):
        if not view.done():
            view.set_exception(SessionQueryError('session-search aborted', 'SESSION_QUERY_ABORTED'))
    remove = signal.add_listener('abort', aborted)
    def settled(job):
        remove()
        error = asyncio.CancelledError() if job.cancelled() else job.exception()
        if view.done():
            return
        if error is not None:
            if isinstance(error, ThrownValueError):
                wrapped = RuntimeError('session-search dependency rejected with a non-Error value')
                wrapped.cause = error.value
                error = wrapped
            view.set_exception(error)
        else:
            view.set_result(job.result())
    operation.add_done_callback(settled)
    try:
        return await view
    except asyncio.CancelledError:
        remove()
        raise


def header_dict(header):
    return header.to_dict() if hasattr(header, 'to_dict') else dict(header)


def json_text(value):
    return stringify_json(value)


def observe(header, events):
    detached_header, detached_events = copy.deepcopy(header), copy.deepcopy(list(events))
    fingerprint = base64.urlsafe_b64encode(hashlib.sha256(json_text(dict(
        header=header_dict(detached_header), events=detached_events)).encode('utf-8')).digest()).decode('ascii').rstrip('=')
    session_id = header_dict(detached_header)['id']
    return dict(header=detached_header,
                documents=build_session_event_search_documents(session_id, detached_events), fingerprint=fingerprint)


def snapshots(entries):
    if not isinstance(entries, list):
        raise RuntimeError('persistence snapshots must be an array')
    result = {}
    for entry in entries:
        revision = entry.get('revision') if isinstance(entry, dict) else getattr(entry, 'revision', None)
        if not isinstance(revision, str):
            raise RuntimeError('persistence snapshot revision must be a string')
        header = copy.deepcopy(entry['header'] if isinstance(entry, dict) else entry.header)
        session_id = header_dict(header)['id']
        if session_id in result:
            raise RuntimeError('persistence listed duplicate session "' + session_id + '"')
        result[session_id] = dict(header=header, revision=revision)
    return result


def same_snapshots(first, second):
    if first.keys() != second.keys():
        return False
    for session_id, before in first.items():
        after = second[session_id]
        if before['revision'] != after['revision']:
            return False
        first_header, second_header = header_dict(before['header']), header_dict(after['header'])
        for name in HEADER_COLUMNS:
            left, right = first_header.get(name), second_header.get(name)
            if name == 'delegationDepth':
                left, right = left or 0, right or 0
            if left != right:
                return False
    return True


class SqliteSessionQueryEngine(SessionQueryService):
    def __init__(self, ctx, config):
        resolved = resolve_config(config)
        super().__init__(ctx, open_at='never', persisted_inspect_concurrency=resolved['persistedInspectConcurrency'],
                         read_window_max=resolved['readWindowMax'])
        self.config = resolved
        self.open_at = resolved['openAt']
        self._instance = str(uuid.uuid4())
        self._ready = None
        self._db = None
        self._binding = dict(identity=object(), service=None)
        self._last_identity = None
        self._persistence_epoch = 0
        self._global_generation = 0
        self._local_generation = 0
        self._closed = False
        self._close_job = None
        self._tail = asyncio.get_event_loop().create_future()
        self._tail.set_result(None)
        def bind(child):
            binding = dict(identity=object(), service=child.get('sessionPersistence'))
            self._binding = binding
            def release():
                if self._binding is binding:
                    self._binding = dict(identity=object(), service=None)
            child.effect(lambda: release)
        self._optional = ctx.inject(['sessionPersistence'], bind)
        ctx.effect(lambda: self._optional.dispose)
        ctx.effect(lambda: self.close)

    async def initialize(self):
        if self.config['openAt'] == 'startup':
            await self._ensure_ready(None)

    async def _open(self):
        self._db = open_search_database(self.config['path'], self.config['journalMode'])
        generation = self._db.prepare('SELECT global_generation FROM search_state WHERE singleton = 1').get()['global_generation']
        self._global_generation = self._local_generation = generation

    async def _ensure_ready(self, signal):
        if self._ready is None:
            self._ready = asyncio.ensure_future(self._open())
        try:
            await wait_with_abort(self._ready, signal)
        except Exception as error:
            if isinstance(error, SessionQueryError) and error.code == 'SESSION_QUERY_ABORTED':
                raise
            failure = failure_value(error)
            raise SessionQueryError('session-search SQLite index failed to open: ' + error_message(failure),
                                    'SESSION_QUERY_INDEX_FAILED', failure) from error

    def _enqueue(self, signal, operation):
        prior = self._tail
        gate = asyncio.get_event_loop().create_future()
        async def chained():
            await asyncio.shield(prior)
            await asyncio.shield(gate)
        self._tail = asyncio.ensure_future(chained())
        async def run():
            try:
                if self._closed:
                    raise index_closed()
                await wait_with_abort(prior, signal)
                if self._closed:
                    raise index_closed()
                check_abort(signal)
                return await operation()
            finally:
                if not gate.done():
                    gate.set_result(None)
        return asyncio.ensure_future(run())

    def close(self):
        if self._close_job is None:
            self._closed = True
            async def finish():
                await asyncio.shield(self._tail)
                if self._ready is not None:
                    try:
                        await asyncio.shield(self._ready)
                    except BaseException:
                        pass
                if self._db is not None:
                    self._db.close()
                    self._db = None
            self._close_job = asyncio.ensure_future(finish())
        return self._close_job

    def _search(self, request, options, events):
        try:
            self._assert_search_enabled()
            owned = (normalize_event_request if events else normalize_session_request)(request, self.config)
        except Exception as error:
            async def rejected(reason=error):
                raise reason
            return rejected()
        signal = (options or {}).get('signal')
        async def operation():
            await self._ensure_ready(signal)
            binding = await self._reconcile(signal)
            check_abort(signal)
            target = self._target(owned['sessionId'], binding) if events else None
            generation = target['generation'] if events else str(self._global_generation)
            fingerprint = normalized_identity(owned)
            offset = decode_cursor(owned['cursor'], self._instance, 'events' if events else 'sessions',
                                   fingerprint, generation) if 'cursor' in owned else 0
            rows = self._query(owned, offset, binding, events)
            items = [self._event_hit(row) if events else dict(header=row_header(row), live=row['live'] == 1,
                     persisted=row['persisted'] == 1, bestMatch=self._event_hit(row)) for row in rows[:owned['limit']]]
            result = dict(items=items)
            if len(rows) > owned['limit']:
                result['nextCursor'] = encode_cursor(dict(version=1, instance=self._instance,
                    scope='events' if events else 'sessions', fingerprint=fingerprint,
                    generation=generation, offset=offset + owned['limit']))
            return dict(session=target['header'], **result) if events else result
        return self._enqueue(signal, operation)

    def searchSessions(self, request, options=None):
        return self._search(request, options, False)

    def searchEvents(self, request, options=None):
        return self._search(request, options, True)

    async def _observe_stable(self, indexed, signal):
        for attempt in range(2):
            check_abort(signal)
            binding = self._binding
            persistence = binding['service']
            sessions = self.ctx.get('sessions')
            initially_live = {session.id for session in sessions.list()}
            persisted = {}
            if persistence is not None:
                try:
                    reusable = self._last_identity is None or self._last_identity is binding['identity']
                    before = await persistence.listSnapshots(signal)
                    check_abort(signal)
                    persisted = snapshots(before)
                    for session_id, entry in persisted.items():
                        if reusable and indexed.get(session_id, {}).get('revision') == entry['revision']:
                            continue
                        if session_id in initially_live or sessions.get(session_id) is not None:
                            continue
                        check_abort(signal)
                        loaded = inspection_source(await persistence.inspect(session_id, signal))
                        check_abort(signal)
                        assert_headers_compatible(entry['header'], loaded['header'])
                        entry['loaded'] = observe(loaded['header'], loaded['events'])
                    check_abort(signal)
                    after = snapshots(await persistence.listSnapshots(signal))
                    check_abort(signal)
                    if not same_snapshots(persisted, after) or self._binding is not binding:
                        continue
                except Exception as error:
                    if (signal is not None and signal.aborted) or (
                            isinstance(error, SessionQueryError) and error.code == 'SESSION_QUERY_ABORTED'):
                        raise SessionQueryError('session-search aborted', 'SESSION_QUERY_ABORTED', failure_value(error)) from error
                    if self._binding is not binding:
                        continue
                    if isinstance(error, SessionQueryError):
                        raise
                    failure = failure_value(error)
                    raise SessionQueryError('session-search persistence observation failed: ' + error_message(failure),
                                            'SESSION_QUERY_PERSISTENCE_FAILED', failure) from error
            live = {}
            for session in sessions.list():
                entry = observe(session.header, session.events)
                if session.id in persisted:
                    assert_headers_compatible(entry['header'], persisted[session.id]['header'])
                live[session.id] = entry
            if initially_live != live.keys():
                continue
            return dict(binding=binding, persisted=persisted, live=live)
        raise SessionQueryError('session-search persistence observation did not stabilize after one retry',
                                'SESSION_QUERY_PERSISTENCE_FAILED')

    async def _reconcile(self, signal):
        check_abort(signal)
        database = self._require_db()
        persisted_rows = {row['id']: row for row in database.prepare('SELECT id,revision,generation FROM persisted_sessions').all()}
        live_rows = {row['id']: row for row in database.prepare('SELECT id,fingerprint,persisted,generation FROM temp.live_sessions').all()}
        observation = await self._observe_stable(persisted_rows, signal)
        check_abort(signal)
        persistent_changes = [entry for entry in observation['persisted'].values() if 'loaded' in entry]
        persistent_deletes = [session_id for session_id in persisted_rows if session_id not in observation['persisted']]
        if observation['binding']['service'] is None:
            persistent_changes = persistent_deletes = []
        live_changes = [entry for session_id, entry in observation['live'].items()
                        if live_rows.get(session_id, {}).get('fingerprint') != entry['fingerprint']
                        or live_rows.get(session_id, {}).get('persisted') != int(session_id in observation['persisted'])]
        live_deletes = [session_id for session_id in live_rows if session_id not in observation['live']]
        pointer_changed = self._last_identity is not None and self._last_identity is not observation['binding']['identity']
        writes = bool(persistent_changes or persistent_deletes or live_changes or live_deletes)
        main_generation = database.prepare('SELECT global_generation FROM search_state WHERE singleton=1').get()['global_generation']
        if persistent_changes or persistent_deletes:
            main_generation += 1
        local_generation = self._local_generation
        replacements = []
        for entry in live_changes:
            local_generation = max(local_generation, main_generation) + 1
            replacements.append((entry, local_generation))
        if writes:
            began = False
            try:
                database.exec('BEGIN IMMEDIATE')
                began = True
                for session_id in persistent_deletes:
                    self._delete('persisted', session_id)
                for entry in persistent_changes:
                    self._replace('persisted', entry['loaded'], main_generation, entry['revision'])
                if persistent_changes or persistent_deletes:
                    database.prepare('UPDATE search_state SET global_generation=? WHERE singleton=1').run(main_generation)
                for session_id in live_deletes:
                    self._delete('live', session_id)
                for entry, generation in replacements:
                    self._replace('live', entry, generation, int(header_dict(entry['header'])['id'] in observation['persisted']))
                database.exec('COMMIT')
            except Exception as error:
                if began:
                    try:
                        database.exec('ROLLBACK')
                    except Exception:
                        pass
                raise SessionQueryError('session-search reconciliation failed: ' + error_message(error),
                                        'SESSION_QUERY_INDEX_FAILED', error) from error
        if writes or pointer_changed:
            self._global_generation += 1
        if pointer_changed:
            self._persistence_epoch += 1
        self._local_generation = local_generation
        self._last_identity = observation['binding']['identity']
        return observation['binding']

    def _delete(self, source, session_id):
        prefix = 'persisted' if source == 'persisted' else 'temp.live'
        database = self._require_db()
        database.prepare('DELETE FROM ' + prefix + '_docs WHERE session_id=?').run(session_id)
        database.prepare('DELETE FROM ' + prefix + '_sessions WHERE id=?').run(session_id)

    def _replace(self, source, entry, generation, qualifier):
        header = header_dict(entry['header'])
        self._delete(source, header['id'])
        prefix = 'persisted' if source == 'persisted' else 'temp.live'
        columns = 'id,version,created_at,cwd,parent_session,seed_length,delegation_depth,agent_preset,'
        columns += 'revision,generation' if source == 'persisted' else 'fingerprint,persisted,generation'
        values = [header.get(name) for name in ('id', 'version', 'createdAt', 'cwd', 'parentSession', 'seedLength', 'delegationDepth', 'agentPreset')]
        values.extend([qualifier, generation] if source == 'persisted' else [entry['fingerprint'], qualifier, generation])
        database = self._require_db()
        database.prepare('INSERT INTO ' + prefix + '_sessions(' + columns + ') VALUES(' + ','.join('?' for value in values) + ')').run(*values)
        insert = database.prepare('INSERT INTO ' + prefix + '_docs(text,session_id,seq,type,time,surface,codepoint_length) VALUES(?,?,?,?,?,?,?)')
        for document in entry['documents']:
            text = sanitize_fts_text(document['text'])
            insert.run(text, document['sessionId'], document['seq'], document['type'], document['time'], document['surface'], len(text))

    def _query(self, request, offset, binding, events):
        event_where = build_event_where(request['filters'] if events else request['eventFilters'])
        session_where = dict(sql='', params=[], predicateCount=1) if events else build_session_where(request['sessionFilters'])
        assert_predicate_count(session_where['predicateCount'] + event_where['predicateCount'])
        where = ' AND '.join(clause for clause in (["session_id = ?"] if events else [session_where['sql']]) + [event_where['sql']] if clause)
        expression = quote_fts_data(request['query'])
        visible = int(binding['service'] is not None)
        parameters = ['\ufdd0', '\ufdd1', expression, visible, visible, '\ufdd0', '\ufdd1', expression, '\ufdd0', 3]
        parameters.extend([request['sessionId']] if events else session_where['params'])
        parameters.extend(event_where['params'])
        parameters.extend([int(request['limit']) + 1, offset])
        assert_binding_count(len(parameters))
        if events:
            sql = SELECTED_DOCUMENTS + ' SELECT * FROM matched WHERE ' + where + ' ORDER BY match_count DESC,document_length ASC,time DESC,seq DESC LIMIT ? OFFSET ?'
        else:
            sql = SELECTED_DOCUMENTS + ', filtered AS (SELECT * FROM matched ' + ('WHERE ' + where if where else '') + '''),
                ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY session_id ORDER BY match_count DESC,document_length ASC,time DESC,seq DESC) AS event_rank FROM filtered)
                SELECT * FROM ranked WHERE event_rank=1 ORDER BY match_count DESC,document_length ASC,time DESC,session_id ASC,seq DESC LIMIT ? OFFSET ?'''
        return self._require_db().prepare(sql).all(*parameters)

    def _target(self, session_id, binding):
        database = self._require_db()
        for prefix in ('temp.live', 'persisted'):
            if prefix == 'persisted' and binding['service'] is None:
                continue
            row = database.prepare('SELECT id AS session_id,version,created_at,cwd,parent_session,seed_length,delegation_depth,agent_preset,generation FROM ' + prefix + '_sessions WHERE id=?').get(session_id)
            if row is not None:
                generation = 'live:' + str(row['generation']) if prefix == 'temp.live' else 'persisted:{}:{}'.format(self._persistence_epoch, row['generation'])
                return dict(header=row_header(row), generation=generation)
        raise SessionQueryError('session "' + session_id + '" not found', 'SESSION_QUERY_SESSION_NOT_FOUND')

    def _event_hit(self, row):
        return dict(sessionId=row['session_id'], seq=row['seq'], type=row['type'], time=row['time'],
                    surface=row['surface'], snippet=make_snippet(row['marked_text'], int(self.config['snippetChars'])))

    def _require_db(self):
        if self._db is None:
            raise index_closed()
        return self._db


def row_header(row):
    return SessionHeader(row['session_id'], version=row['version'], created_at=row['created_at'], cwd=row['cwd'],
                         parent_session=row['parent_session'], seed_length=row['seed_length'],
                         delegation_depth=row['delegation_depth'], agent_preset=row['agent_preset'])


def normalized_identity(request):
    def nullable_compare(left, right):
        if left == right:
            return 0
        if left is None:
            return -1
        if right is None:
            return 1
        return locale_compare(left, right)
    def canonical(filters):
        values = []
        for clause in filters:
            if 'values' in clause:
                values.append(dict(clause, values=sorted(clause['values'], key=cmp_to_key(nullable_compare))))
            else:
                values.append(dict(kind=clause['kind'], **{'from': clause.get('from'), 'to': clause.get('to')}))
        return sorted(values, key=cmp_to_key(lambda left, right: locale_compare(json_text(left), json_text(right))))
    if 'sessionId' in request:
        return json_text(dict(scope='events', sessionId=request['sessionId'], query=request['query'],
                              filters=canonical(request['filters']), limit=request['limit']))
    return json_text(dict(scope='sessions', query=request['query'], sessionFilters=canonical(request['sessionFilters']),
                          eventFilters=canonical(request['eventFilters']), limit=request['limit']))


def encode_cursor(payload):
    return base64.urlsafe_b64encode(json_text(payload).encode('utf-8')).decode('ascii').rstrip('=')


def decode_cursor(cursor, instance, scope, fingerprint, generation):
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode('utf-8'))
        if (not isinstance(payload, dict) or type(payload.get('version')) not in (int, float) or payload['version'] != 1
                or payload.get('instance') != instance or payload.get('scope') != scope
                or payload.get('fingerprint') != fingerprint or not integer(payload.get('offset'))
                or not 0 <= payload['offset'] <= 9007199254740991):
            raise ValueError('cursor does not belong to this normalized request')
    except Exception as error:
        raise SessionQueryError('session-search cursor is invalid', 'SESSION_QUERY_INVALID_CURSOR', error) from error
    if payload.get('generation') != generation:
        raise SessionQueryError('session-search cursor is stale because its relevant corpus changed', 'SESSION_QUERY_STALE_CURSOR')
    return int(payload['offset'])


SELECTED_DOCUMENTS = '''WITH candidates AS (
    SELECT pd.session_id,ps.version,ps.created_at,ps.cwd,ps.parent_session,ps.seed_length,ps.delegation_depth,ps.agent_preset,
        0 AS live,1 AS persisted,CAST(pd.seq AS INTEGER) AS seq,pd.type,CAST(pd.time AS INTEGER) AS time,pd.surface,
        highlight(persisted_docs,0,?,?) AS marked_text,CAST(pd.codepoint_length AS INTEGER) AS document_length
    FROM persisted_docs AS pd JOIN persisted_sessions AS ps ON ps.id=pd.session_id
    WHERE persisted_docs MATCH ? AND ?=1 AND NOT EXISTS(SELECT 1 FROM temp.live_sessions AS ls WHERE ls.id=pd.session_id)
    UNION ALL
    SELECT ld.session_id,ls.version,ls.created_at,ls.cwd,ls.parent_session,ls.seed_length,ls.delegation_depth,ls.agent_preset,
        1 AS live,CASE WHEN ?=1 THEN ls.persisted ELSE 0 END AS persisted,CAST(ld.seq AS INTEGER) AS seq,ld.type,
        CAST(ld.time AS INTEGER) AS time,ld.surface,highlight(live_docs,0,?,?) AS marked_text,
        CAST(ld.codepoint_length AS INTEGER) AS document_length
    FROM temp.live_docs AS ld JOIN temp.live_sessions AS ls ON ls.id=ld.session_id WHERE live_docs MATCH ?
    ),matched AS (SELECT *,(length(CAST(marked_text AS BLOB))-length(CAST(replace(marked_text,?, '') AS BLOB)))/? AS match_count FROM candidates)'''


class SqliteSessionQueryPlugin(Plugin):
    id = 'session-query-sqlite'
    name = '@deepseek-ai/dsh-session-query-sqlite'
    inject = ['sessions']

    async def apply(self, ctx):
        config = dict(self.config)
        config.setdefault('path', ':memory:')
        service = SqliteSessionQueryEngine(ctx, config)
        ctx.set_service('sessionQuery', service)
        await service.initialize()
