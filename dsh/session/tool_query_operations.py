from dsh.cordis.utils import _UNDEFINED
from dsh.llm.error import HarnessError
from dsh.session.preparations import throw_aborted
from dsh.session.session_query import SessionQueryError
from dsh.session import tool_query_boundary as boundary
from dsh.session import tool_query_input as tool_input
from dsh.session import tool_query_presentation as presentation
from dsh.session import tool_query_workspace as workspace


async def collect_pages(max_results, signal, request, accept):
    items, seen, cursor = [], set(), _UNDEFINED
    while True:
        throw_aborted(signal)
        page = await request(cursor)
        throw_aborted(signal)
        for item in page['items']:
            if not accept(item):
                continue
            if len(items) == max_results:
                return dict(items=items, capped=True)
            items.append(item)
        if 'nextCursor' not in page:
            return dict(items=items, capped=False)
        if page['nextCursor'] in seen:
            raise SessionQueryError('session-search provider repeated a continuation cursor', 'SESSION_QUERY_INVALID_CURSOR')
        seen.add(page['nextCursor'])
        cursor = page['nextCursor']


async def execute_session_search(ctx, args, execution, max_results):
    caller = workspace.caller_of(execution)
    cwd = caller['header'].get('cwd', _UNDEFINED)
    if cwd is _UNDEFINED:
        raise HarnessError('cross-session search is unavailable because the caller session has no workspace', 'SESSION_QUERY_TOOL_UNAUTHORIZED')
    query = tool_input.normalize_query(args['query'])
    session_filters = tool_input.build_session_filters(args)
    event_filters = tool_input.build_event_filters(args.get('event_seq_from'), args.get('event_seq_to'),
                                                  args.get('event_time_from'), args.get('event_time_to'),
                                                  args.get('event_types'), args.get('event_surfaces'))
    requested_parents = tool_input.materialize_parent_ids(args.get('parent_session_ids'))
    if requested_parents is not None or args.get('include_root_sessions') is True:
        authorized = set() if requested_parents is None else await workspace.authorize_session_ids(ctx, caller, requested_parents, execution.signal)
        parents = [parent for parent in requested_parents or [] if parent in authorized]
        if args.get('include_root_sessions') is True:
            parents.append(None)
        if not parents:
            return presentation.format_empty_session_search()
        session_filters.append(dict(kind='parent', values=parents))
    session_filters.append(dict(kind='cwd', values=[cwd]))
    async def request(cursor):
        payload = dict(query=query, sessionFilters=session_filters, eventFilters=event_filters)
        if cursor is not _UNDEFINED:
            payload['cursor'] = cursor
        return await boundary.call(ctx, execution.signal, 'session search', lambda: ctx.get('sessionQuery').searchSessions(payload, dict(signal=execution.signal)))
    collected = await collect_pages(max_results, execution.signal, request,
                                    lambda hit: hit['header']['id'] != caller['id'] and workspace.record_authorized(hit, caller))
    parent_ids = [hit['header']['parentSession'] for hit in collected['items'] if 'parentSession' in hit['header']]
    authorized_parents = await workspace.authorize_session_ids(ctx, caller, parent_ids, execution.signal)
    titles = await workspace.read_titles(ctx, caller, [hit['header']['id'] for hit in collected['items']], execution.signal)
    return presentation.format_session_search(collected, titles, authorized_parents)


async def execute_event_search(ctx, args, execution, max_results):
    caller = workspace.caller_of(execution)
    session_id = workspace.target_id(args, caller)
    await workspace.authorize_target(ctx, caller, session_id, execution.signal)
    query = tool_input.normalize_query(args['query'])
    sequence = tool_input.sequence_range(args.get('seq_from'), args.get('seq_to'))
    if session_id == caller['id']:
        step = next((event for event in reversed(caller['events']) if event['type'] == 'step/start'), None)
        if step is None:
            raise HarnessError('current-session search requires an active step boundary', 'SESSION_QUERY_TOOL_NO_CURRENT_STEP')
        sequence['to'] = min(sequence.get('to', tool_input.MAX_SAFE_INTEGER), step['seq'] - 1)
    title = await workspace.read_title(ctx, caller, session_id, execution.signal)
    if 'from' in sequence and 'to' in sequence and sequence['from'] > sequence['to']:
        return presentation.format_event_search(session_id, title, dict(items=[], capped=False))
    filters = tool_input.build_event_filters(sequence.get('from'), sequence.get('to'), args.get('time_from'), args.get('time_to'),
                                            args.get('event_types'), args.get('surfaces'))
    async def request(cursor):
        payload = dict(sessionId=session_id, query=query, filters=filters)
        if cursor is not _UNDEFINED:
            payload['cursor'] = cursor
        page = await boundary.call(ctx, execution.signal, 'event search', lambda: ctx.get('sessionQuery').searchEvents(payload, dict(signal=execution.signal)))
        workspace.assert_observed_authorized(caller, session_id, page['session'])
        return page
    collected = await collect_pages(max_results, execution.signal, request, lambda hit: True)
    return presentation.format_event_search(session_id, title, collected)


async def execute_session_trace(ctx, args, execution):
    caller = workspace.caller_of(execution)
    session_id = workspace.target_id(args, caller)
    await workspace.authorize_target(ctx, caller, session_id, execution.signal)
    trace = await boundary.call(ctx, execution.signal, 'session lineage trace', lambda: ctx.get('sessionQuery').traceSession(session_id, execution.signal))
    workspace.assert_observed_authorized(caller, session_id, trace['target']['header'])
    ancestors, ancestor_boundary = [], False
    for ancestor in trace['ancestors']:
        if not workspace.record_authorized(ancestor, caller):
            ancestor_boundary = True
            break
        ancestors.append(ancestor)
    if len(ancestors) == len(trace['ancestors']) and not trace['complete']:
        ancestor_boundary = True
    descendants = workspace.authorize_descendants(trace['descendants'], caller)
    visible_ids = [trace['target']['header']['id']] + [record['header']['id'] for record in ancestors] + workspace.descendant_ids(descendants)
    titles = await workspace.read_titles(ctx, caller, visible_ids, execution.signal)
    return presentation.format_session_trace(trace, ancestors, ancestor_boundary, descendants, titles)


async def execute_event_trace(ctx, args, execution):
    tool_input.assert_non_negative_safe_integer('seq', args['seq'])
    caller = workspace.caller_of(execution)
    session_id = workspace.target_id(args, caller)
    await workspace.authorize_target(ctx, caller, session_id, execution.signal)
    trace = await boundary.call(ctx, execution.signal, 'event trace', lambda: ctx.get('sessionQuery').traceEvent(dict(sessionId=session_id, seq=args['seq']), execution.signal))
    workspace.assert_observed_authorized(caller, session_id, trace['session'])
    title = await workspace.read_title(ctx, caller, session_id, execution.signal)
    return presentation.format_event_trace(session_id, title, trace)


async def execute_event_read(ctx, args, execution):
    tool_input.assert_non_negative_safe_integer('seq', args['seq'])
    for name in ('before', 'after'):
        if name in args:
            tool_input.assert_non_negative_safe_integer(name, args[name])
    caller = workspace.caller_of(execution)
    session_id = workspace.target_id(args, caller)
    await workspace.authorize_target(ctx, caller, session_id, execution.signal)
    payload = dict(sessionId=session_id, seq=args['seq'])
    payload.update({name: args[name] for name in ('before', 'after') if name in args})
    window = await boundary.call(ctx, execution.signal, 'event read', lambda: ctx.get('sessionQuery').readEvent(payload, execution.signal))
    workspace.assert_observed_authorized(caller, session_id, window['session'])
    title = await workspace.read_title(ctx, caller, session_id, execution.signal)
    return presentation.format_event_read(session_id, title, window)
