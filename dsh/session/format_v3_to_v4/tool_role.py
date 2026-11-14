"""First-class tool-role messages, ported from fixed 0.2.2-rc.3 Source."""
from dsh.core.session.json import UNDEFINED
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError


def _extensions(value, fields, owner):
    return {'plugin:' + owner + ':' + key: item for key, item in value.items() if key not in fields}


def liftToolResult(event):
    data = event.get('data')
    if event['type'] != 'tool/result' or not isinstance(data, dict):
        return event
    message = data.get('message')
    if not isinstance(message, dict) or message.get('role') != 'user':
        return event
    source = message.get('source')
    call_id = source.get('callId') if isinstance(source, dict) else None
    content = message.get('content')
    wrapper = content[0] if isinstance(content, list) and len(content) == 1 else None
    identity = message.get('id')
    subject = 'format v3 {} at seq {}'.format(event['type'], event['seq'])
    if (not isinstance(identity, str) or not identity or not isinstance(source, dict)
            or source.get('kind') != 'tool' or not isinstance(call_id, str) or not call_id
            or not isinstance(wrapper, dict) or wrapper.get('type') != 'tool-result'
            or wrapper.get('toolCallId') != call_id):
        raise SessionFormatError(subject + ' requires exactly one tool-result wrapper matching its tool source')
    error = wrapper.get('isError', UNDEFINED)
    if error is not UNDEFINED and not isinstance(error, bool):
        raise SessionFormatError(subject + ' tool-result isError must be boolean')
    result = wrapper.get('content')
    if not isinstance(result, list):
        raise SessionFormatError(subject + ' tool-result content must be an array')
    if any(isinstance(block, dict) and block.get('type') == 'tool-result' for block in result):
        raise SessionFormatUnsupportedMigrationError(subject + ' contains a nested tool-result unsupported by this converter')
    target = dict(role='tool', source=source, toolCallId=call_id, content=result)
    if error is not UNDEFINED:
        target['isError'] = error
    target['id'] = identity
    target.update(_extensions(message, {'id', 'role', 'source', 'content'}, 'message'))
    target.update(_extensions(wrapper, {'type', 'toolCallId', 'content', 'isError'}, 'result'))
    return dict(event, data=dict(data, message=target))


def assertV4ToolResultMessage(event):
    if event['type'] != 'tool/result':
        return
    subject = 'format v4 {} at seq {}'.format(event['type'], event['seq'])
    data = event.get('data')
    if not isinstance(data, dict):
        raise SessionFormatError(subject + ' data must be an object')
    message = data.get('message')
    if not isinstance(message, dict):
        raise SessionFormatError(subject + ' message must be an object')
    identity, source = message.get('id'), message.get('source')
    call_id = message.get('toolCallId')
    source_call_id = source.get('callId', UNDEFINED) if isinstance(source, dict) else UNDEFINED
    if not isinstance(identity, str) or not identity:
        raise SessionFormatError(subject + ' requires a first-class message with a string id')
    if message.get('role') != 'tool':
        raise SessionFormatError(subject + ' requires a tool-role message')
    if not isinstance(call_id, str) or not call_id or source_call_id != call_id:
        raise SessionFormatError(subject + ' requires toolCallId matching its tool source')
    if not isinstance(source, dict) or source.get('kind') != 'tool':
        raise SessionFormatError(subject + ' requires a tool source')
    content, error = message.get('content'), message.get('isError', UNDEFINED)
    if not isinstance(content, list):
        raise SessionFormatError(subject + ' requires array content')
    if any(isinstance(block, dict) and block.get('type') == 'tool-result' for block in content):
        raise SessionFormatError(subject + ' content must not contain a released tool-result wrapper')
    if error is not UNDEFINED and not isinstance(error, bool):
        raise SessionFormatError(subject + ' isError must be boolean when present')
    if data.get('error', UNDEFINED) is not UNDEFINED and error is not True:
        raise SessionFormatError(subject + ' carries error metadata for a non-error tool result')
