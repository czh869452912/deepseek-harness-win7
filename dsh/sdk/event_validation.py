"""Validate only the wire event fields consumed by SDK readers."""
from collections.abc import Mapping
from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import UNDEFINED
from .errors import SdkProtocolError


def _record(value):
    return isinstance(value, Mapping)


def _json(value):
    return 'undefined' if value is UNDEFINED else stringify_json(value)


def validated_turn_end_reason(value):
    if not _record(value) or not isinstance(value.get('kind'), str):
        raise SdkProtocolError('turn/end carried no reason envelope: ' + _json(value))
    if value['kind'] == 'aborted':
        reason = value.get('reason')
        if not _record(reason) or not isinstance(reason.get('kind'), str):
            raise SdkProtocolError('turn/end carried a malformed aborted reason: ' + _json(value))
        if reason['kind'] == 'hook':
            if not isinstance(reason.get('reason'), str):
                raise SdkProtocolError('turn/end carried a malformed hook abort reason: ' + _json(value))
        elif reason['kind'] not in ('user', 'parent', 'disposed', 'legacy'):
            raise SdkProtocolError('turn/end carried an unknown abort reason: ' + _json(value))
    return value


def validated_session_event(value):
    if not _record(value) or not isinstance(value.get('type'), str):
        raise SdkProtocolError('session.event carried no event envelope: ' + _json(value))
    if value['type'] == 'assistant/message':
        data = value.get('data'); message = data.get('message') if _record(data) else None
        content = message.get('content') if _record(message) else None
        if not isinstance(content, list) or not all(_record(block) and isinstance(block.get('type'), str) for block in content):
            raise SdkProtocolError('assistant/message event carried malformed content: ' + _json(value))
    if value['type'] == 'turn/end':
        data = value.get('data')
        if not _record(data):
            raise SdkProtocolError('turn/end event carried malformed data: ' + _json(value))
        validated_turn_end_reason(data.get('reason', UNDEFINED))
    return value
