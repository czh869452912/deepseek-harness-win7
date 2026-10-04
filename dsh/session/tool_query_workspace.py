from dsh.cordis.utils import _UNDEFINED
from dsh.llm.error import HarnessError
from dsh.session.tool_query_boundary import call, sanitize_error, unauthorized_target


def caller_of(execution):
    agent = getattr(execution, 'agent', None)
    if agent is None:
        raise HarnessError('session query tools require an agent-bound caller', 'SESSION_QUERY_TOOL_MISSING_AGENT')
    session = agent.session
    return dict(id=session.id, header=session.header, events=session.events)


def target_id(args, caller):
    return args['session_id'] if 'session_id' in args else caller['id']


def header_authorized(header, caller):
    caller_cwd = caller['header'].get('cwd', _UNDEFINED)
    if header['id'] == caller['id']:
        return header.get('cwd', _UNDEFINED) == caller_cwd
    return caller_cwd is not _UNDEFINED and header.get('cwd', _UNDEFINED) == caller_cwd


def record_authorized(record, caller):
    return header_authorized(record['header'], caller)


def assert_observed_authorized(caller, target, observed):
    if observed['id'] != target or not header_authorized(observed, caller):
        raise unauthorized_target()


async def authorize_target(ctx, caller, target, signal):
    if target == caller['id']:
        return
    cwd = caller['header'].get('cwd', _UNDEFINED)
    if cwd is _UNDEFINED:
        raise unauthorized_target()
    filters = [dict(kind='id', values=[target]), dict(kind='cwd', values=[cwd])]
    records = await call(ctx, signal, 'target authorization', lambda: ctx.get('sessionQuery').filterSessions(filters, signal))
    if len(records) != 1:
        raise unauthorized_target()


async def authorize_session_ids(ctx, caller, session_ids, signal):
    unique = list(dict.fromkeys(session_ids))
    authorized = {caller['id']} if caller['id'] in unique else set()
    cwd = caller['header'].get('cwd', _UNDEFINED)
    other = [session_id for session_id in unique if session_id != caller['id']]
    if cwd is _UNDEFINED or not other:
        return authorized
    filters = [dict(kind='id', values=other), dict(kind='cwd', values=[cwd])]
    records = await call(ctx, signal, 'session-id authorization', lambda: ctx.get('sessionQuery').filterSessions(filters, signal))
    requested = set(other)
    for record in records:
        if record['header']['id'] in requested and record_authorized(record, caller):
            authorized.add(record['header']['id'])
    return authorized


def unavailable_title(ctx, error):
    sanitized = sanitize_error(ctx, 'title observation item', error)
    if sanitized.code == 'SESSION_QUERY_TOOL_UNAUTHORIZED':
        raise sanitized
    return dict(text='untitled', unavailableCode=sanitized.code)


async def read_titles(ctx, caller, session_ids, signal):
    result = {}
    observations = await call(ctx, signal, 'title observation', lambda: ctx.get('sessionQuery').readTitleSnapshots(session_ids, signal))
    for observation in observations:
        if observation['status'] == 'rejected':
            result[observation['sessionId']] = unavailable_title(ctx, observation['reason'])
            continue
        assert_observed_authorized(caller, observation['sessionId'], observation['value']['session'])
        title = observation['value'].get('title')
        result[observation['sessionId']] = dict(text=title['title'] if title is not None else 'untitled')
    return result


async def read_title(ctx, caller, session_id, signal):
    return (await read_titles(ctx, caller, [session_id], signal)).get(session_id)


def title_text(view):
    if 'unavailableCode' not in view:
        return view['text']
    return view['text'] + ' (title unavailable: ' + view['unavailableCode'] + ')'


def authorize_descendants(nodes, caller):
    result = []
    pending = [(node, result) for node in reversed(nodes)]
    while pending:
        node, target = pending.pop()
        if not record_authorized(node['session'], caller):
            target.append(None)
            continue
        projected = dict(record=node['session'], descendants=[])
        target.append(projected)
        pending.extend((child, projected['descendants']) for child in reversed(node['descendants']))
    return result


def visit_descendants(nodes):
    pending = [(node, 0) for node in reversed(nodes)]
    while pending:
        node, depth = pending.pop()
        yield node, depth
        if node is not None:
            pending.extend((child, depth + 1) for child in reversed(node['descendants']))


def descendant_ids(nodes):
    return [node['record']['header']['id'] for node, depth in visit_descendants(nodes) if node is not None]
