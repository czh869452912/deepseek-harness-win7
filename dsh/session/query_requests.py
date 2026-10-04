import re

from dsh.cordis.json_text import stringify_json
from dsh.session.session_query import SessionQueryError, materialize_session_result_filters
from dsh.session.session_query import materialize_session_event_result_filters, sanitize_fts_text


MAX_PAGE_LIMIT = 9007199254740990
VARIABLE_LIMIT = 32766
OUTER_PREDICATE_LIMIT = 14
WHITESPACE = r'[\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]'


def normalize_query(value):
    if not isinstance(value, str):
        raise SessionQueryError('session-search query must be text', 'SESSION_QUERY_INVALID_QUERY')
    query = re.sub(WHITESPACE + '+', ' ', re.sub('^' + WHITESPACE + '+|' + WHITESPACE + '+$', '', value))
    if not query:
        raise SessionQueryError('session-search query must contain non-whitespace text', 'SESSION_QUERY_INVALID_QUERY')
    if '\0' in query:
        raise SessionQueryError('session-search query must not contain NUL', 'SESSION_QUERY_INVALID_QUERY')
    return sanitize_fts_text(query)


def normalize_limit(value, limits):
    limit = limits['defaultLimit'] if value is None else value
    maximum = min(limits['maxLimit'], MAX_PAGE_LIMIT)
    if (type(limit) not in (int, float) or not 1 <= limit <= maximum or int(limit) != limit):
        raise SessionQueryError('session-search limit must be an integer between 1 and ' + stringify_json(maximum),
                                'SESSION_QUERY_INVALID_LIMIT')
    return int(limit)


def metadata_filters(filters):
    if not isinstance(filters, (list, str)):
        raise TypeError('candidates is not iterable')
    for clause in filters:
        if clause is None:
            raise TypeError("Cannot read properties of null (reading 'kind')")
        kind = clause.get('kind') if isinstance(clause, dict) else None
        if kind == 'text':
            raise SessionQueryError('session-search metadata filters do not accept text clauses',
                                    'SESSION_QUERY_INVALID_FILTER')
        if kind not in ('seq', 'time', 'type', 'surface'):
            unknown_filter(clause)
    return materialize_session_event_result_filters(filters)


def normalized_request(request, limits, events=False):
    if events:
        if not isinstance(request.get('sessionId'), str):
            raise SessionQueryError('session-search session id must be text', 'SESSION_QUERY_INVALID_FILTER')
        filters = metadata_filters([] if request.get('filters') is None else request['filters'])
        result = dict(sessionId=request['sessionId'], filters=filters)
    else:
        sessions = materialize_session_result_filters([] if request.get('sessionFilters') is None else request['sessionFilters'])
        events_filters = metadata_filters([] if request.get('eventFilters') is None else request['eventFilters'])
        result = dict(sessionFilters=sessions, eventFilters=events_filters)
    if 'cursor' in request and not isinstance(request['cursor'], str):
        raise SessionQueryError('session-search cursor must be text', 'SESSION_QUERY_INVALID_CURSOR')
    query = normalize_query(request.get('query'))
    limit = normalize_limit(request.get('limit'), limits)
    output = dict(sessionId=result['sessionId'], query=query, filters=result['filters'], limit=limit) if events else dict(
        query=query, sessionFilters=result['sessionFilters'], eventFilters=result['eventFilters'], limit=limit)
    if 'cursor' in request:
        output['cursor'] = request['cursor']
    return output


def normalize_session_request(request, limits):
    return normalized_request(request, limits)


def normalize_event_request(request, limits):
    return normalized_request(request, limits, True)


def assert_binding_count(count):
    if count > VARIABLE_LIMIT:
        raise SessionQueryError("session-search request exceeds SQLite's portable 32766-variable limit; reduce filter values",
                                'SESSION_QUERY_INVALID_FILTER')


def assert_predicate_count(count):
    if count > OUTER_PREDICATE_LIMIT:
        raise SessionQueryError('session-search request exceeds the supported SQLite FTS5 outer-predicate budget of 14; reduce filters',
                                'SESSION_QUERY_INVALID_FILTER')


def unknown_filter(clause):
    kind = clause.get('kind') if isinstance(clause, dict) else None
    detail = '"' + kind + '"' if isinstance(kind, str) else '(missing)'
    raise SessionQueryError('session filter contains unknown kind ' + detail, 'SESSION_QUERY_INVALID_FILTER')


def build_where(filters, events=False):
    clauses = []
    parameters = []
    def bindings(values):
        assert_binding_count(len(parameters) + len(values))
        parameters.extend(values)
        return ', '.join('?' for value in values)
    columns = dict(seq='seq', time='time', type='type', surface='surface') if events else dict(
        id='session_id', cwd='cwd', parent='parent_session', **{'created-at':'created_at'})
    ranges = ('seq', 'time') if events else ('created-at',)
    for clause in filters:
        kind = clause.get('kind')
        if not events and kind == 'availability':
            values = list(dict.fromkeys(clause['values']))
            if not values:
                clauses.append('0')
            elif len(values) == 1:
                if values[0] not in ('live', 'persisted'):
                    raise SessionQueryError('session availability filter contains unknown value "' + str(values[0]) + '"',
                                            'SESSION_QUERY_INVALID_FILTER')
                clauses.append(values[0] + ' = 1')
        elif kind in columns:
            column = columns[kind]
            if kind in ranges:
                for name, operator in [('from', '>='), ('to', '<=')]:
                    if name in clause:
                        assert_binding_count(len(parameters) + 1)
                        clauses.append('CAST(' + column + ' AS INTEGER) ' + operator + ' ?')
                        parameters.append(clause[name])
            else:
                values = clause['values']
                if not values:
                    clauses.append('0')
                elif kind in ('cwd', 'parent'):
                    concrete = [value for value in values if value is not None]
                    parts = [column + ' IN (' + bindings(concrete) + ')'] if concrete else []
                    if None in values:
                        parts.append(column + ' IS NULL')
                    clauses.append('(' + ' OR '.join(parts) + ')')
                else:
                    clauses.append(column + ' IN (' + bindings(values) + ')')
        else:
            unknown_filter(clause)
    assert_predicate_count(len(clauses))
    return dict(sql=' AND '.join(clauses), params=parameters, predicateCount=len(clauses))


def build_session_where(filters):
    return build_where(filters)


def build_event_where(filters):
    return build_where(filters, True)


def make_snippet(marked_text, max_chars):
    characters = []
    match_start = None
    for character in marked_text:
        if character == '\ufdd0':
            if match_start is None:
                match_start = len(characters)
        elif character == '\ufdd1':
            continue
        elif re.fullmatch(WHITESPACE, character):
            if characters and characters[-1] != ' ':
                characters.append(' ')
        else:
            characters.append(character)
    if characters and characters[-1] == ' ':
        characters.pop()
    clean = ''.join(characters)
    if len(characters) <= max_chars:
        return clean
    if max_chars == 1:
        return '…'
    matched = min(match_start if match_start is not None else 0, len(characters) - 1)
    start = max(0, matched - max_chars // 3)
    prefix = '…' if start else ''
    suffix = '…'
    length = max_chars - len(prefix) - len(suffix)
    if length < 1:
        start = matched
        suffix = ''
        length = max_chars - len(prefix)
    elif matched >= start + length:
        start = matched - length + 1
    end = min(len(characters), start + length)
    if end == len(characters):
        suffix = ''
        length = max_chars - len(prefix)
        start = max(0, end - length)
    end = min(len(characters), start + length)
    return prefix + ''.join(characters[start:end]) + suffix
