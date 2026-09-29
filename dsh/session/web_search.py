"""Live-preferred FTS pages with current-surface authorization and revision cursors."""
import base64
import hashlib
import json

from dsh.core.surface import fold_surface, is_surface_event
from dsh.session.session_query import SessionQueryError, extract_session_event_text, quote_fts_data


async def search_sessions(service, request, options):
    signal = options.get('signal')
    def check():
        if signal is not None:
            signal.throw_if_aborted()
    check()
    service.ensure_search()
    limit = request.get('limit', 20)
    if type(limit) is not int or not 1 <= limit <= 9007199254740990:
        raise SessionQueryError('invalid search limit', 'SESSION_QUERY_INVALID_REQUEST')
    records = await service.listSessions(signal)
    headers, revisions, documents = {}, [], []
    for record in records:
        check()
        header = record['header']
        observed = await service.observeSession(header.id, dict(signal=signal, projectionMode='none'))
        try:
            headers[header.id] = header
            revisions.append([header.to_dict(), observed.cursor])
            current = set(fold_surface(list(observed.events)).nodes)
            for event in observed.events:
                text = extract_session_event_text(event)
                if not text:
                    continue
                surface = 'current' if event['seq'] in current else 'shadowed' if is_surface_event(event) else 'log-only'
                admitted = True
                for predicate in request.get('eventFilters', []):
                    key = predicate['kind']
                    if key == 'type':
                        admitted = admitted and event['type'] in predicate['values']
                    elif key == 'surface':
                        admitted = admitted and surface in predicate['values']
                    else:
                        raise SessionQueryError('unsupported event metadata filter: ' + key, 'SESSION_QUERY_INVALID_REQUEST')
                if admitted:
                    documents.append((header.id, event['seq'], event['type'], surface, text))
        finally:
            observed.dispose()
    check()
    identity = dict(query=request['query'], eventFilters=request.get('eventFilters', []), revisions=revisions)
    generation = hashlib.sha256(json.dumps(identity, ensure_ascii=True, sort_keys=True).encode('utf-8')).hexdigest()
    offset = 0
    if request.get('cursor') is not None:
        try:
            cursor = json.loads(base64.urlsafe_b64decode(request['cursor'].encode('ascii')))
            if cursor['generation'] != generation:
                raise SessionQueryError('search corpus changed', 'SESSION_QUERY_STALE_CURSOR')
            offset = cursor['offset']
            if type(offset) is not int or offset < 0:
                raise ValueError('invalid offset')
        except SessionQueryError:
            raise
        except Exception as error:
            raise SessionQueryError('invalid search cursor', 'SESSION_QUERY_INVALID_CURSOR', error) from error
    # The durable source is authoritative; rebuild this transient query view so
    # cold logs, replacements and newly attached sessions cannot leave stale hits.
    conn = service._conn
    conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS session_remote_fts USING fts5(session_id UNINDEXED, seq UNINDEXED, event_type UNINDEXED, surface UNINDEXED, content)')
    with conn:
        conn.execute('DELETE FROM session_remote_fts')
        conn.executemany('INSERT INTO session_remote_fts VALUES (?, ?, ?, ?, ?)', documents)
    rows = conn.execute("SELECT session_id, seq, event_type, surface, snippet(session_remote_fts, 4, '', '', '…', 40), bm25(session_remote_fts) FROM session_remote_fts WHERE session_remote_fts MATCH ? ORDER BY bm25(session_remote_fts), session_id, seq", (quote_fts_data(request['query']),)).fetchall()
    seen, hits = set(), []
    for sid, seq, kind, surface, snippet, score in rows:
        if sid in seen:
            continue
        seen.add(sid)
        hits.append(dict(header=headers[sid], bestMatch=dict(sessionId=sid, seq=seq, type=kind, surface=surface, snippet=snippet, score=score)))
    result = dict(items=hits[offset:offset + limit])
    if offset + limit < len(hits):
        result['nextCursor'] = base64.urlsafe_b64encode(json.dumps(dict(generation=generation, offset=offset + limit)).encode('utf-8')).decode('ascii')
    return result
