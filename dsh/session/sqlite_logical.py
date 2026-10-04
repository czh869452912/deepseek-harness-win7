import math

from dsh.core.session import SESSION_FORMAT_VERSION, KNOWN_SESSION_EVENT_TYPES, SessionHeader
from dsh.core.session.types import adopt_session_event
from dsh.session.persistence import SessionFormatUnsupportedError, SessionPersistenceCorruptionError as CorruptionError


class SessionPersistenceNotFoundError(FileNotFoundError):
    name = 'SessionPersistenceNotFoundError'

    def __init__(self, identity):
        super().__init__('session "%s" not found' % identity)
        self.sessionId = identity


class SessionPersistenceCorruptionError(CorruptionError):
    name = 'SessionPersistenceCorruptionError'

    def __init__(self, identity, cause):
        prefix = 'TypeError' if isinstance(cause, TypeError) else 'Error'
        super().__init__('stored session "%s" failed validation: %s: %s' % (identity, prefix, cause))
        self.cause = cause


def header_from_stored(metadata):
    return SessionHeader(session_id=metadata['id'], version=metadata['version'], created_at=metadata['createdAt'],
        cwd=metadata.get('cwd'), parent_session=metadata.get('parentSession'), seed_length=metadata.get('seedLength'),
        origin=metadata.get('origin'), delegation_depth=metadata.get('delegationDepth'), agent_preset=metadata.get('agentPreset'))


def logical_numbers(value):
    result = [None]
    pending = [(result, 0, value)]
    while pending:
        parent, key, current = pending.pop()
        if isinstance(current, dict):
            detached = {}
            parent[key] = detached
            pending.extend((detached, name, item) for name, item in current.items())
        elif isinstance(current, list):
            detached = [None] * len(current)
            parent[key] = detached
            pending.extend((detached, index, item) for index, item in enumerate(current))
        else:
            parent[key] = int(current) if type(current) is float and math.isfinite(current) and current.is_integer() else current
    return result[0]


def safe_integer(value):
    return type(value) is int and abs(value) <= 9007199254740991


def only_keys(value, required, optional=()):
    return set(required) <= set(value) and set(value) <= set(required) | set(optional)


def needs_legacy_prefix(event):
    data = event.get('data')
    if event['type'] == 'steering/message':
        return True
    if not isinstance(data, dict):
        return False
    if event['type'] == 'user/message':
        return 'id' not in data and 'content' in data
    if event['type'] == 'assistant/message':
        return 'message' not in data and 'content' in data
    if event['type'] == 'tool/result':
        return 'message' not in data and 'callId' in data
    return False


def migrate_event(event, identity, message_ids):
    data = event.get('data')
    kind = event['type']
    def malformed():
        raise ValueError('session "%s" contains malformed pre-react-loop %s at seq %s' % (identity, kind, event['seq']))
    if kind == 'turn/start' and isinstance(data, dict) and 'trigger' in data:
        trigger = data['trigger']
        if (not safe_integer(data.get('turn')) or data['turn'] < 1 or not only_keys(data, ['turn', 'trigger'])
                or not isinstance(trigger, dict) or not isinstance(trigger.get('kind'), str) or not trigger['kind']):
            malformed()
        event['data'] = dict(turn=data['turn'])
        return event
    if kind == 'steering/message':
        if not isinstance(data, dict):
            malformed()
        if isinstance(data.get('message'), dict) and safe_integer(data.get('turn')) and only_keys(data, ['turn', 'message']):
            event.update(type='user/message', data=data['message'])
            return event
        if not safe_integer(data.get('turn')) or not only_keys(data, ['turn', 'content', 'source']):
            malformed()
        event.update(type='user/message', data=dict(content=data['content'], source=data['source'],
                     id='legacy-message:%s:%s' % (identity, event['seq']), role='user'))
        return event
    if kind == 'turn/end' and isinstance(data, dict):
        reason = data.get('reason')
        if (not safe_integer(data.get('turn')) or data['turn'] < 1 or not only_keys(data, ['turn', 'reason'])
                or not isinstance(reason, dict) or not isinstance(reason.get('kind'), str)):
            malformed()
        reason_kind = reason['kind']
        if reason_kind in ('completed', 'blocked', 'max-tokens', 'interrupted'):
            if not only_keys(reason, ['kind']):
                malformed()
        elif reason_kind in ('aborted', 'disposed'):
            if reason_kind == 'aborted' and 'reason' in reason:
                return event
            if not only_keys(reason, ['kind']):
                malformed()
            data['reason'] = dict(kind='aborted', reason=dict(kind='legacy' if reason_kind == 'aborted' else 'disposed'))
        elif reason_kind == 'error' and 'error' not in reason:
            if not safe_integer(reason.get('step')) or reason['step'] < 0:
                malformed()
            failure = reason.get('failure')
            if (isinstance(failure, dict) and only_keys(reason, ['kind', 'step', 'failure'])
                    and only_keys(failure, ['message', 'code'], ['status', 'providerRetryAfterMs', 'requestId'])
                    and isinstance(failure.get('message'), str) and isinstance(failure.get('code'), str)
                    and all(name not in failure or type(failure[name]) in (int, float) for name in ('status', 'providerRetryAfterMs'))
                    and ('requestId' not in failure or isinstance(failure['requestId'], str))):
                data['reason'] = dict(kind='error', error=failure)
            else:
                keys = ['kind', 'step', 'message'] + (['code'] if 'code' in reason else [])
                if (not only_keys(reason, keys) or not isinstance(reason.get('message'), str)
                        or ('code' in reason and not isinstance(reason['code'], str))):
                    malformed()
                data['reason'] = dict(kind='error', error=dict(message=reason['message'], code=reason.get('code', 'UNKNOWN')))
        return event
    if not isinstance(data, dict):
        return event
    identifier = 'legacy-message:%s:%s' % (identity, event['seq'])
    if kind == 'user/message':
        if not set(data) & {'id', 'role', 'message'} and {'content', 'source'} <= set(data):
            data.update(id=identifier, role='user')
    elif kind == 'assistant/message':
        if 'message' not in data and {'content', 'provenance'} <= set(data):
            provenance = data.pop('provenance')
            source = dict(provenance) if isinstance(provenance, dict) else {}
            source['kind'] = 'model'
            content = data.pop('content')
            data['message'] = dict(id=identifier, role='assistant', content=content, source=source)
    elif kind == 'tool/result':
        if 'message' not in data and {'callId', 'content', 'isError'} <= set(data):
            surface = event.get('surfaceOp')
            if isinstance(surface, dict) and surface.get('op') == 'replace' and type(surface.get('start')) in (int, float):
                identifier = message_ids.get(surface['start'])
            call_id, content, is_error = data.pop('callId'), data.pop('content'), data.pop('isError')
            data['message'] = dict(id=identifier, role='user', source=dict(kind='tool', callId=call_id),
                content=[dict(type='tool-result', toolCallId=call_id, content=content, isError=is_error)])
    return event


def validate_inspection(inspection, identity):
    metadata = inspection.meta
    if metadata.id != identity:
        raise ValueError('stored session identity mismatch: requested "%s", header contains "%s"' % (identity, metadata.id))
    if metadata.version != SESSION_FORMAT_VERSION:
        if metadata.version > SESSION_FORMAT_VERSION:
            reason = ('session "%s" uses log format v%s, but this harness reads only v%s: the log was written by a newer harness — upgrade the harness to open it'
                      % (identity, metadata.version, SESSION_FORMAT_VERSION))
        else:
            reason = 'session "%s" uses log format v%s, older than the supported v%s, and this build ships no upgrade path for it' % (identity, metadata.version, SESSION_FORMAT_VERSION)
        raise SessionFormatUnsupportedError(reason)
    events = logical_numbers(inspection.events)
    for legacy in ('request/header-delta', 'mode/set'):
        for event in events:
            if event['type'] == legacy:
                raise ValueError('session "%s" contains unsupported legacy %s event at seq %s' % (identity, legacy, event['seq']))
    for event in events:
        if event['type'] == 'request/header' and isinstance(event.get('data'), dict) and event['data'].get('reason') == 'fallback':
            raise ValueError('session "%s" contains unsupported legacy request/header reason "fallback" at seq %s' % (identity, event['seq']))
    message_ids = {}
    for index, event in enumerate(events):
        event = adopt_session_event(migrate_event(event, identity, message_ids))
        events[index] = event
        data = event.get('data')
        message = data if event['type'] == 'user/message' else data.get('message') if isinstance(data, dict) else None
        if isinstance(message, dict) and isinstance(message.get('id'), str):
            message_ids[event['seq']] = message['id']
    for event in events:
        if event['type'] not in KNOWN_SESSION_EVENT_TYPES:
            raise SessionFormatUnsupportedError('session "%s" contains event type "%s" (seq %s) unknown to this harness; refusing to interpret the log — it was likely written by a newer harness' % (identity, event['type'], event['seq']))
    inspection.events = events
    return inspection
