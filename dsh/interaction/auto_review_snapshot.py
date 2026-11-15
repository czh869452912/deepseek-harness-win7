"""Durable, authority-labelled review inputs from the current Session surface.

Port of experimental/auto-review's snapshotAutoReview at 38a6a5c9. This
intentionally reads complete action history: projections do not expose the
started native/PTC prefix needed to verify a pending call.
"""
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.core.session.json import deep_freeze
from dsh.jobs.pump import field
from dsh.session.sqlite_json import parse_json


def review_json(value, level=0):
    if isinstance(value, (dict, list)):
        if not value:
            return '{}' if isinstance(value, dict) else '[]'
        pad = '  ' * (level + 1)
        if isinstance(value, dict):
            items = [stringify_json(key) + ': ' + review_json(value[key], level + 1)
                     for key in _js_own_enumerable_keys(value)]
            left, right = '{', '}'
        else:
            items = [review_json(item, level + 1) for item in value]
            left, right = '[', ']'
        return left + '\n' + pad + (',\n' + pad).join(items) + '\n' + '  ' * level + right
    return stringify_json(value)


def _fail(message):
    raise RuntimeError('auto-review: ' + message)


def _parsed(raw):
    if raw == '':
        return {}
    try:
        return parse_json(raw)
    except (ValueError, TypeError):
        return raw


def _step(data):
    return (data['turn'], data['step'])


def _key(step, call_id):
    return '%s\0%s\0%s' % (stringify_json(step[0]), stringify_json(step[1]), call_id)


def _shown_key(mode, key):
    return mode + '\0' + key


def _schema_entry(mode, value, name=None):
    name = value['name'] if name is None else name
    if not isinstance(field(value, 'description'), str) or not isinstance(field(value, 'parameters'), dict):
        _fail('the pending %s tool schema is incomplete' % ('native' if mode == 'native' else 'PTC'))
    return dict(kind='tool-schema', role='fact', mode=mode, name=name,
                description=field(value, 'description'), parameters=field(value, 'parameters'))


def _browser(source):
    return source['kind'] == 'user' and isinstance(source.get('rpcId'), str)


def _creation_prompts(session, events):
    all_prompts, boundary = set(), False
    header = session.header
    for event in events:
        if event['type'] == 'subagent/descriptor':
            boundary = True
            continue
        if (boundary and event['type'] == 'user/message'
                and event['data']['source']['kind'] == 'user' and not _browser(event['data']['source'])):
            all_prompts.add(event['seq'])
            if session.isOwnSeq(event['seq']) and header.get('origin') == 'subagent' and header.get('parentSession') is not None:
                return event['seq'], all_prompts
            boundary = False
    return None, all_prompts


def _text_role(source, seq, prompts, session):
    own, all_prompts = prompts
    parent = session.header.get('parentSession')
    if seq == own or (parent is not None and source['kind'] == 'agent-message' and source.get('senderSessionId') == parent):
        return 'direct-parent-instruction'
    if seq in all_prompts:
        return 'fact'
    if source['kind'] == 'user':
        if own is None and session.header.get('origin') == 'subagent' and parent is not None and session.isOwnSeq(seq) and not _browser(source):
            return 'fact'
        return 'user-instruction'
    return 'checkpoint' if source['kind'] == 'compact-checkpoint' else 'fact'


def snapshot_auto_review(agent, execution, cwd, shown):
    session = field(agent, 'session')
    events, nodes, header = session.snapshotEvents(), list(field(session.surface, 'nodes')), session.requestHeader()
    if header is None or not header['config']['provider'] or not header['config']['model']:
        _fail('no complete request-header route is available')
    native, starts, by_parent, current = {}, {}, {}, None
    for event in events:
        kind, data = event['type'], event['data']
        if kind == 'tool/call':
            native.setdefault(_key(_step(data), data['callId']), []).append(event)
    scoped_starts = []
    for event in events:
        kind, data = event['type'], event['data']
        if kind in ('turn/start', 'turn/end', 'step/end'):
            current = None
        elif kind == 'step/start':
            current = _step(data)
        elif kind == 'tool/ptc-dispatch-start':
            if current is None:
                _fail('a PTC call has no owning step in the session log')
            scoped_starts.append((event, current))
    prompts = _creation_prompts(session, events)
    for event, step in scoped_starts:
        data = event['data']
        sub_key = _key(step, data['subCallId'])
        if sub_key in starts:
            _fail('a PTC call identity is ambiguous in the session log')
        start = dict(event=event, step=step)
        starts[sub_key] = start
        by_parent.setdefault(_key(step, data['parentCallId']), []).append(start)
    if current is None:
        _fail('the pending call has no open step in the session log')
    root_id, call_id, parent = field(execution, 'rootCallId'), field(execution, 'callId'), field(execution, 'parent')
    root_calls = native.get(_key(current, root_id), [])
    if len(root_calls) != 1:
        _fail('the pending root call is missing or ambiguous in the session log')
    root_call = root_calls[0]
    ptc = None if parent is None else starts.get(_key(current, call_id))
    if parent is not None and ptc is None:
        _fail('the pending PTC call is missing or ambiguous in the session log')
    history, emitted, visible_parents = [], set(), set()

    def push(mode, key, name, raw, schema=None):
        schema = shown.get(key) if schema is None else schema
        if schema is not None:
            identity = stringify_json(schema)
            if identity not in emitted:
                emitted.add(identity)
                history.append(schema)
        history.append(dict(kind='tool-call', role='fact', mode=mode, name=name, arguments=raw))

    passed_root = False
    for seq in nodes:
        event = events[seq]
        kind, data = event['type'], event['data']
        if kind == 'user/message':
            source, content = data['source'], data['content']
            if source['kind'] == 'tool':
                continue
            if source['kind'] == 'agent-instructions':
                if content:
                    history.append(dict(kind='user-message', role='constraint', source=source, content=content))
            else:
                history.extend(dict(kind='user-message', role=_text_role(source, event['seq'], prompts, session)
                                    if block['type'] == 'text' else 'fact', source=source, content=[block]) for block in content)
            continue
        if kind != 'assistant/message':
            continue
        step, unstarted = _step(data), False
        is_current = step == current
        for block in data['message']['content']:
            if block['type'] != 'tool-call':
                continue
            key = _key(step, block['id'])
            is_root = is_current and block['id'] == root_id
            if is_root and passed_root:
                _fail('the pending root call is ambiguous in the current surface')
            calls, children = native.get(key, []), by_parent.get(key, [])
            if len(calls) > 1:
                _fail('a native call identity is ambiguous in the session log')
            if not calls:
                if is_current and not passed_root:
                    _fail('a visible call before the pending root is missing from the session log')
                if children:
                    _fail('an unstarted visible call has logged PTC dispatches')
                unstarted = True
                continue
            call = calls[0]
            if unstarted:
                _fail('visible native call logs do not form a started prefix')
            if call['data']['name'] != block['name'] or call['data']['arguments'] != block['arguments']:
                _fail('a visible tool call disagrees with its logged action')
            visible_parents.add(key)
            if call is not root_call or parent is not None:
                push('native', _shown_key('native', key), call['data']['name'], call['data']['arguments'])
            for start in children:
                if start is ptc:
                    continue
                inner = start['event']['data']
                push('ptc-inner', _shown_key('ptc-inner', _key(start['step'], inner['subCallId'])), inner['name'], review_json(inner['arguments']))
            if is_root:
                passed_root = True
    if not passed_root:
        _fail('the pending root call is missing from the current surface')
    name, arguments = field(execution, 'name'), field(execution, 'arguments')
    if ptc is None:
        logged = root_call['data']
        if logged['name'] != name or stringify_json(_parsed(logged['arguments'])) != stringify_json(arguments):
            _fail('the pending native call disagrees with its logged action')
        tools = header.get('tools')
        candidates = [tool for tool in tools if isinstance(tool, dict) and tool.get('name') == name] if isinstance(tools, list) else []
        if len(candidates) != 1:
            _fail('the pending native tool schema is missing or ambiguous')
        pending = dict(key=_shown_key('native', _key(current, root_id)), schema=_schema_entry('native', candidates[0], name))
        push('native', pending['key'], name, logged['arguments'], pending['schema'])
    else:
        logged = ptc['event']['data']
        if (_key(ptc['step'], logged['parentCallId']) not in visible_parents or logged['rootCallId'] != root_id
                or logged['name'] != name or stringify_json(logged['arguments']) != stringify_json(arguments)):
            _fail('the pending PTC call disagrees with its logged action')
        schema = field(execution, 'schema')
        if schema is None or field(schema, 'name') != name:
            _fail('the pending PTC binding schema is missing or inconsistent')
        pending = dict(key=_shown_key('ptc-inner', _key(current, call_id)), schema=_schema_entry('ptc-inner', schema, name))
        push('ptc-inner', pending['key'], name, review_json(logged['arguments']), pending['schema'])
    return deep_freeze(dict(provider=header['config']['provider'], model=header['config']['model'], cwd=cwd, history=history, pending=pending))


def review_messages(snapshot):
    texts = ['ENVIRONMENT\n' + review_json(dict(cwd=snapshot['cwd']))] + [review_json(entry) for entry in snapshot['history']]
    return [dict(role='user', content=[dict(type='text', text=text)]) for text in texts]
