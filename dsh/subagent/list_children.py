"""Read-only v4 discovery through parent-owned, live-preferred catalogs."""
from dsh.core.cancellation import aborted
from dsh.core.session.json import UNDEFINED
from dsh.subagent.errors import SubagentError
from dsh.subagent.names import is_agent_name, join_agent_path


def _check(signal):
    if aborted(signal):
        raise SubagentError('subagent listing was cancelled', 'CANCELLED')


async def list_children(ctx, parent_session_id, signal=None):
    query = ctx.get('sessionQuery')
    if query is None:
        raise SubagentError('listing subagents requires the sessionQuery service (load @deepseek-ai/dsh-session-query)',
                            'SUBAGENT_CONTROL_QUERY_UNAVAILABLE')
    parent = await query.observeSession(parent_session_id, {} if signal is None else dict(signal=signal))
    try:
        projections = parent.projections
        entries = (projections or {}).get('values', {}).get('subagentCatalog', UNDEFINED)
        if entries is UNDEFINED:
            raise SubagentError('listing subagents requires the registered subagentCatalog projection',
                                'SUBAGENT_CONTROL_PROJECTIONS_UNAVAILABLE')
        return entries
    finally:
        parent.dispose()


async def list_descendants(ctx, root_session_id, signal=None):
    sessions = ctx.get('sessions')
    if sessions is None:
        raise SubagentError('listing subagents requires the session store (load @deepseek-ai/dsh-session)',
                            'SUBAGENT_CONTROL_SESSION_STORE_UNAVAILABLE')
    async def read(identity):
        _check(signal)
        try:
            children = await list_children(ctx, identity, signal)
        except Exception:
            _check(signal)
            raise
        _check(signal)
        return children
    stack = [(entry, root_session_id, 1, '') for entry in reversed(await read(root_session_id))]
    visited, result = {root_session_id}, []
    while stack:
        entry, parent_id, depth, parent_path = stack.pop()
        identity = entry['id']
        if identity in visited:
            continue
        visited.add(identity)
        path = join_agent_path(parent_path, entry.get('name', UNDEFINED))
        position = dict(parentId=parent_id, depth=depth)
        if path is not UNDEFINED:
            position['path'] = path
        try:
            children = [] if entry['mode'] == 'external' else await read(identity)
        except SubagentError:
            raise
        except Exception as error:
            code = getattr(error, 'code', None)
            result.append(dict(kind='diagnostic', id=identity, reason='corrupt' if code in
                ('SESSION_QUERY_CORRUPT_SESSION', 'SESSION_QUERY_SOURCE_CONFLICT') else 'unavailable', **position))
            continue
        if entry['mode'] == 'unknown':
            result.append(dict(kind='diagnostic', id=identity, reason='unsupported', **position))
        else:
            result.append(dict({key: value for key, value in entry.items() if key != 'createdAt'},
                kind='child', activity='inactive' if sessions.get(identity) is None else 'running',
                hasChildren=bool(children), **position))
        stack.extend((child, identity, depth+1, path) for child in reversed(children))
    return result


async def resolve_agent_path(ctx, root_session_id, name, signal):
    segments = name.split('/')
    if not all(is_agent_name(segment) for segment in segments):
        return UNDEFINED
    current = root_session_id
    for index, segment in enumerate(segments):
        children = await list_children(ctx, current, signal)
        child = next((entry for entry in children if entry.get('name') == segment), None)
        if child is None:
            return UNDEFINED
        if index < len(segments)-1 and child['mode'] not in ('continuable', 'one-shot'):
            return UNDEFINED
        current = child['id']
    return current


listChildren = list_children
listDescendants = list_descendants
resolveAgentPath = resolve_agent_path
