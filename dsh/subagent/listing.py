"""Read-only projection-backed child catalogs with bounded cold observations."""
import asyncio
from collections import deque
from dsh.subagent.errors import SubagentError


def check(signal):
    if signal is not None and signal.aborted:
        raise SubagentError('subagent listing was cancelled', 'CANCELLED')


def child_row(sid, identity, activity, has_children):
    row = dict(kind='child', id=sid, mode=identity['mode'], activity=activity, hasChildren=has_children)
    if 'label' in identity:
        row['label'] = identity['label']
    return row


async def list_children(ctx, root, signal=None, descendants=False):
    services = {}
    for name, code in (('sessionProjections', 'PROJECTIONS'), ('sessions', 'SESSION_STORE'), ('sessionQuery', 'QUERY')):
        services[name] = ctx.get(name)
        if services[name] is None:
            raise SubagentError('listing requires ' + name, 'SUBAGENT_CONTROL_' + code + '_UNAVAILABLE')
    check(signal)
    query, projections, sessions = services['sessionQuery'], services['sessionProjections'], services['sessions']
    try:
        records = await query.listSessions(signal)
    except Exception:
        check(signal)
        raise
    check(signal)
    corpus, parents, children = {}, set(), {}
    for record in records:
        header = record['header']
        live = sessions.get(header.id)
        corpus[header.id] = dict(header=live.header if live is not None else header, live=live)
    for record in corpus.values():
        header = record['header']
        if header.parentSession is not None:
            children.setdefault(header.parentSession, []).append(record)
            if header.origin == 'subagent':
                parents.add(header.parentSession)
    for siblings in children.values():
        siblings.sort(key=lambda record: (record['header'].createdAt, record['header'].id))
    candidates, visited = [], {root}
    stack = [(record, root, 1) for record in reversed(children.get(root, []))]
    while stack:
        record, parent_id, depth = stack.pop()
        sid = record['header'].id
        if sid in visited:
            continue
        visited.add(sid)
        if record['header'].origin == 'subagent':
            candidates.append((record, parent_id, depth))
        if descendants:
            stack.extend((child, sid, depth + 1) for child in reversed(children.get(sid, [])))
    rows = [None] * len(candidates)
    cold = deque()
    for index, (record, _, _) in enumerate(candidates):
        header, live = record['header'], record['live']
        if live is None:
            cold.append((index, header))
            continue
        try:
            identity = projections.snapshot(live, ['subagent'])['values'].get('subagent')
        except Exception:
            rows[index] = dict(kind='diagnostic', id=header.id, reason='corrupt')
            continue
        if identity is not None and identity['seq'] >= (header.seedLength or 0):
            rows[index] = child_row(header.id, identity, 'running', header.id in parents)
    async def worker():
        while cold:
            index, header = cold.popleft()
            rows[index] = await cold_row(ctx, query, header, header.id in parents, signal)
    # Drain all observers before forwarding any failure/cancellation.
    outcomes = await asyncio.gather(*(worker() for _ in range(min(4, len(cold)))), return_exceptions=True)
    check(signal)
    for result in outcomes:
        if isinstance(result, BaseException):
            raise result
    result = []
    for index, row in enumerate(rows):
        if row is not None:
            if descendants:
                row = dict(row, parentId=candidates[index][1], depth=candidates[index][2])
            result.append(row)
    return result


async def cold_row(ctx, query, header, has_children, signal):
    cache = ctx.get('sessionProjectionCache')
    if cache is not None:
        try:
            cached = cache.cachedSnapshot(header, ['subagent'])
            identity = (cached or {}).get('values', {}).get('subagent')
            if identity is not None and identity['seq'] >= (header.seedLength or 0):
                return child_row(header.id, identity, 'inactive', has_children)
        except Exception:
            pass
    check(signal)
    try:
        observed = await query.observeSession(header.id, {'signal': signal})
    except Exception as error:
        check(signal)
        corrupt = getattr(error, 'code', None) in ('SESSION_QUERY_CORRUPT_SESSION', 'SESSION_QUERY_SOURCE_CONFLICT')
        return dict(kind='diagnostic', id=header.id, reason='corrupt' if corrupt else 'unavailable')
    try:
        check(signal)
        keys = ('version', 'id', 'createdAt', 'cwd', 'parentSession', 'seedLength', 'delegationDepth', 'origin', 'agentPreset')
        identity = (observed.projections or {}).get('values', {}).get('subagent')
        if (any(getattr(observed.header, key) != getattr(header, key) for key in keys) or
                identity is None or identity['seq'] < (header.seedLength or 0)):
            return dict(kind='diagnostic', id=header.id, reason='corrupt')
        return child_row(header.id, identity, 'inactive', has_children)
    finally:
        observed.dispose()
