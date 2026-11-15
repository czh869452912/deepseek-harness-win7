"""Canonical v3 admission, shared by the format catalog and Session integration.

The adjacent format libraries own historical semantics. These checks own the
installed Session boundary, where ordinary plugin payload additions stay open.
"""
import math

from dsh.core.session.json import UNDEFINED
from dsh.core.session.types import ALLOWED_ENVELOPE_KEYS, validate_session_header, assert_adapter_defaults

SESSION_FORMAT_VERSION = 3
SURFACE_EVENT_TYPES = frozenset(('system/message', 'user/message', 'assistant/message', 'tool/result'))
V4_SURFACE_EVENT_TYPES = SURFACE_EVENT_TYPES | {'developer/message'}


def safe(value, nonnegative=False, reject_negative_zero=False):
    return (type(value) in (int, float) and math.isfinite(value) and abs(value) <= 9007199254740991
        and int(value) == value and (not nonnegative or value >= 0)
        and (not reject_negative_zero or value != 0 or math.copysign(1, value) > 0))


def has_provider_model(value):
    return isinstance(value, dict) and all(isinstance(value.get(key), str) and value[key] for key in ('provider', 'model'))


def validateSessionEventData(event, subject, format_version=3):
    data = event.get('data', UNDEFINED)
    if format_version == 4 and event['type'] in V4_SURFACE_EVENT_TYPES and isinstance(data, dict):
        message = data if event['type'] == 'user/message' else data.get('message')
        if isinstance(message, dict):
            developer = event['type'] == 'developer/message'
            if developer != (message.get('role') == 'developer'):
                raise ValueError(subject + ' developer/message and developer role must occur together')
            content = message.get('content')
            if isinstance(content, list):
                changes = [block for block in content if isinstance(block, dict)
                           and block.get('type') in ('tool-addition', 'tool-removal')]
                if message.get('role') != 'developer' and changes:
                    raise ValueError(subject + ' tool-change blocks require developer role')
                if developer:
                    additions = False
                    for block in changes:
                        if not isinstance(block.get('toolName'), str) or not block['toolName']:
                            raise ValueError(subject + ' ' + block['type'] + ' requires a nonempty toolName')
                        if block['type'] == 'tool-addition':
                            additions = True
                            if 'tool' in block:
                                raise ValueError(subject + ' tool-addition must omit inline tool definitions')
                    invalid_header = not safe(data.get('headerSeq'), True, True) if additions else 'headerSeq' in data
                    if invalid_header:
                        raise ValueError(subject + ' requires headerSeq exactly when tool additions are present')
    if event['type'] == 'request/header':
        if not isinstance(data, dict):
            raise ValueError(subject + ' data must be an object')
        header = data.get('header')
        if not isinstance(header, dict):
            raise ValueError(subject + ' header must be an object')
        if 'system' in header:
            raise ValueError(subject + ' must omit header.system; use system/message')
        if isinstance(header.get('tools'), list) and not header['tools']:
            raise ValueError(subject + ' must omit empty tools')
        if isinstance(header.get('adapterDefaults'), dict) and not header['adapterDefaults']:
            raise ValueError(subject + ' must omit empty adapterDefaults')
    elif event['type'] == 'tool/result':
        if not isinstance(data, dict):
            raise ValueError(subject + ' data must be an object')
        if data.get('error', UNDEFINED) is UNDEFINED:
            return
        message = data.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        block = content[0] if isinstance(content, list) and content else None
        if format_version == 4:
            if not isinstance(message, dict) or message.get('isError') is not True:
                raise ValueError(subject + ' error requires message.isError === true')
        elif not isinstance(block, dict) or block.get('isError') is not True:
            raise ValueError(subject + ' error requires message content[0].isError === true')


def assertMessageEventShape(event, subject, format_version=3):
    kind = event['type']
    if kind not in (V4_SURFACE_EVENT_TYPES if format_version == 4 else SURFACE_EVENT_TYPES):
        return
    data = event.get('data')
    message = data if kind == 'user/message' else data.get('message') if isinstance(data, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get('id'), str) or not message['id']:
        raise ValueError(subject + ' lacks an identified message')
    role = {'system/message':'system', 'developer/message':'developer', 'assistant/message':'assistant',
            'user/message':'user', 'tool/result':'tool' if format_version == 4 else 'user'}[kind]
    if message.get('role') != role:
        raise ValueError(subject + ' message must have role "' + role + '"')
    source = message.get('source')
    if not isinstance(source, dict) or not isinstance(source.get('kind'), str) or not source['kind']:
        raise ValueError(subject + ' message has invalid source')
    content = message.get('content')
    if not isinstance(content, list):
        raise ValueError(subject + ' message has invalid content')
    if kind == 'system/message':
        if format_version == 4:
            if source['kind'] != 'system-prompt':
                raise ValueError(subject + ' message must have system-prompt source')
        elif source['kind'] != 'plugin' or not isinstance(source.get('plugin'), str) or not source['plugin']:
            raise ValueError(subject + ' message must have plugin source')
    elif kind == 'assistant/message':
        if source['kind'] != 'model' or not has_provider_model(source):
            raise ValueError(subject + ' message must have model source')
    elif kind == 'tool/result':
        if source['kind'] != 'tool' or not isinstance(source.get('callId'), str) or not source['callId']:
            raise ValueError(subject + ' message must have tool source')
        if format_version == 4:
            if message.get('toolCallId') != source['callId']:
                raise ValueError(subject + ' message has mismatched tool call ids')
        elif len(content) != 1 or not isinstance(content[0], dict) or content[0].get('type') != 'tool-result' or not isinstance(content[0].get('content'), list):
            raise ValueError(subject + ' message must contain one tool-result block')
        elif content[0].get('toolCallId') != source['callId']:
            raise ValueError(subject + ' message has mismatched tool call ids')


def assertCurrentLlmShape(event, index, format_version=3):
    kind, data = event['type'], event['data']
    subject = 'seed %s at index %s' % (kind, index)
    if kind == 'request/header':
        header = data['header']
        config = header.get('config')
        if not has_provider_model(config):
            raise ValueError(subject + ' lacks provider/model')
        effort = config.get('reasoningEffort', UNDEFINED)
        if effort is not UNDEFINED and (not isinstance(effort, str) or not effort):
            raise ValueError(subject + ' has an invalid reasoningEffort')
        assert_adapter_defaults(header.get('adapterDefaults', UNDEFINED), config, index)
        if data.get('reason') not in ('initial', 'resume', 'change', 'series'):
            raise ValueError(subject + ' has an invalid reason')
        if data.get('startsSeries', UNDEFINED) is not UNDEFINED and data['startsSeries'] is not True:
            raise ValueError(subject + ' has an invalid startsSeries marker')
    if kind in (V4_SURFACE_EVENT_TYPES if format_version == 4 else SURFACE_EVENT_TYPES):
        assertMessageEventShape(event, subject, format_version)
    if kind in ('assistant/message', 'assistant/attempt'):
        if not isinstance(data, dict) or not all(safe(data.get(key), True, True) for key in ('turn', 'step')) or not isinstance(data.get('stream'), list):
            raise ValueError(subject + ' has invalid settlement fields')


def assertSessionEventEnvelope(event, index, format_version=3):
    invalid = ValueError('seed event at index %s has an invalid event envelope' % index)
    if (not isinstance(event, dict) or any(key not in ALLOWED_ENVELOPE_KEYS for key in event)
        or not isinstance(event.get('type'), str) or not safe(event.get('seq'), True, True)
        or not safe(event.get('time')) or event.get('data', UNDEFINED) is UNDEFINED
        or event.get('ignorable', UNDEFINED) is not UNDEFINED and event['ignorable'] is not True):
        raise invalid
    validateSessionEventData(event, 'seed %s at index %s' % (event['type'], index), format_version)
    if event['type'] in (V4_SURFACE_EVENT_TYPES if format_version == 4 else SURFACE_EVENT_TYPES) or event['type'] in ('request/header', 'assistant/attempt'):
        assertCurrentLlmShape(event, index, format_version)


def validateCurrentHeader(header, format_version=3):
    return validate_session_header(header.get('id', UNDEFINED), header, expected_version=format_version)


def adoptSessionEvent(event, format_version=3):
    from .current_surface import validateSurfaceMetadata
    from .json import deep_freeze, FrozenDict
    subject = 'session event at seq %s' % event['seq']
    validateSessionEventData(event, subject, format_version)
    validateSurfaceMetadata(event, format_version)
    assertMessageEventShape(event, subject, format_version)
    kind, data = event['type'], event['data']
    if isinstance(data,FrozenDict):
        return event
    if kind == 'user/message':
        event['data'] = deep_freeze(data)
    elif kind in ('system/message', 'assistant/message', 'tool/result') or format_version == 4 and kind == 'developer/message':
        data['message'] = deep_freeze(data['message'])
    return event


def snapshotSessionEvent(event, format_version=3):
    import copy
    return adoptSessionEvent(copy.deepcopy(event), format_version)
