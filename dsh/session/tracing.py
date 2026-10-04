import copy


def analyze_event_log(session_id, events):
    from dsh.core.surface import fold_surface
    from dsh.session.session_query import SessionQueryError
    try:
        folded = fold_surface(events)
    except Exception as error:
        raise SessionQueryError('invalid session surface: ' + str(error),
                                'SESSION_QUERY_INVALID_SURFACE', error) from error
    current = set(folded.nodes)
    replaced_by = {}
    replaced_event_seqs = {}
    for replacement in folded.replacements:
        removed = list(replacement.shadowedSeqs)
        replaced_event_seqs[replacement.seq] = removed
        for removed_seq in removed:
            replaced_by[removed_seq] = replacement.seq
    records = [dict(sessionId=session_id, seq=event['seq'], type=event['type'], time=event['time'],
                    surface='current' if event['seq'] in current else
                    'shadowed' if event['seq'] in replaced_by else 'log-only') for event in events]
    return dict(records=records, replacedBy=replaced_by, replacedEventSeqs=replaced_event_seqs,
                currentSeqs=list(folded.nodes))


def event_target(session_id, events, seq):
    from dsh.cordis.utils import js_to_string
    from dsh.session.session_query import SessionQueryError
    if (type(seq) not in (int, float) or not 0 <= seq < len(events) or int(seq) != seq
            or events[int(seq)]['seq'] != seq):
        raise SessionQueryError('session "' + session_id + '" has no event at seq ' + js_to_string(seq),
                                'SESSION_QUERY_EVENT_NOT_FOUND')
    return events[int(seq)]


def event_records(session_id, events):
    return analyze_event_log(session_id, events)['records']


def current_surface_events(session_id, events):
    from dsh.core.session import snapshot_session_event
    analysis = analyze_event_log(session_id, events)
    return [snapshot_session_event(events[seq]) for seq in analysis['currentSeqs']]


def trace_event(session_id, events, seq):
    target = event_target(session_id, events, seq)
    analysis = analyze_event_log(session_id, events)
    replaced_by = analysis['replacedBy']
    replacement_chain = []
    replacement = replaced_by.get(seq)
    while replacement is not None:
        replacement_chain.append(replacement)
        replacement = replaced_by.get(replacement)
    result = dict(target=analysis['records'][int(seq)], replacementChain=replacement_chain,
                  replacedEventSeqs=list(analysis['replacedEventSeqs'].get(seq, [])),
                  sourceEventSeqs=list(target.get('sourceEventSeqs', [])),
                  derivedEventSeqs=[event['seq'] for event in events if event['seq'] > seq
                                    and seq in event.get('sourceEventSeqs', [])])
    if seq in replaced_by:
        result['replacedBy'] = replaced_by[seq]
    return result


def trace_session(records, session_id):
    from dsh.session.session_query import SessionQueryError
    by_id = {record['header'].id: record for record in records}
    target = by_id.get(session_id)
    if target is None:
        raise SessionQueryError('session "' + session_id + '" not found',
                                'SESSION_QUERY_SESSION_NOT_FOUND')
    ancestors = []
    seen = {session_id}
    parent_id = target['header'].parentSession
    unresolved = None
    while parent_id is not None:
        if parent_id in seen:
            raise SessionQueryError('session lineage contains a cycle at "' + parent_id + '"',
                                    'SESSION_QUERY_INVALID_LINEAGE')
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            unresolved = parent_id
            break
        ancestors.append(parent)
        parent_id = parent['header'].parentSession
    children_by_parent = {}
    for record in records:
        parent_id = record['header'].parentSession
        if parent_id is not None:
            children_by_parent.setdefault(parent_id, []).append(record)
    for children in children_by_parent.values():
        children.sort(key=lambda record: (record['header'].createdAt, record['header'].id))
    descendants = []
    stack = [(session_id, descendants)]
    while stack:
        identity, output = stack.pop()
        nodes = [dict(session=copy.deepcopy(child), descendants=[])
                 for child in children_by_parent.get(identity, [])]
        output.extend(nodes)
        stack.extend((node['session']['header'].id, node['descendants']) for node in reversed(nodes))
    result = dict(target=copy.deepcopy(target), ancestors=[copy.deepcopy(record) for record in ancestors],
                  descendants=descendants, complete=unresolved is None)
    if unresolved is not None:
        result['unresolvedParentId'] = unresolved
    else:
        result['root'] = copy.deepcopy(ancestors[-1] if ancestors else target)
    return result
