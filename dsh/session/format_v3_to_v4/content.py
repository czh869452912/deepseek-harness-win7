"""Namespace historical extension content without interpreting nested JSON."""
from dsh.core.session.json import UNDEFINED
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from .sources import mapEventMessages

V3_BLOCK_TYPES = frozenset(('text', 'reasoning', 'image', 'file', 'tool-call', 'tool-result'))


def _block(value, subject):
    if not isinstance(value, dict) or not isinstance(value.get('type'), str):
        raise SessionFormatError(subject + ' requires content blocks with string type tags')
    return value if value['type'] in V3_BLOCK_TYPES else dict(value, type='plugin:' + value['type'])


def migrateV3Content(value, subject):
    if not isinstance(value, list):
        raise SessionFormatError(subject + ' content must be an array')
    mapped = [_block(block, '{}[{}]'.format(subject, index)) for index, block in enumerate(value)]
    return value if all(a is b for a, b in zip(mapped, value)) else mapped


def _message(message, subject):
    original = message.get('content', UNDEFINED)
    content = migrateV3Content(original, subject)
    return message if content is original else dict(message, content=content)


def _chunk(value, subject):
    if not isinstance(value, dict):
        return value
    if value.get('type') == 'block-end':
        original = value.get('block', UNDEFINED)
        block = _block(original, subject + '.block')
        return value if block is original else dict(value, block=block)
    if value.get('type') != 'block-start':
        return value
    original = value.get('blockType')
    if not isinstance(original, str):
        raise SessionFormatError(subject + ' blockType must be a string')
    return value if original in V3_BLOCK_TYPES else dict(value, blockType='plugin:' + original)


def migrateV3EventContent(event):
    subject = 'format v3 {} at seq {}'.format(event['type'], event['seq'])
    mapped = mapEventMessages(event, lambda message: _message(message, subject))
    data = mapped.get('data')
    if not isinstance(data, dict):
        return mapped
    original_data = data
    fields = ('summary', 'rawOutput') if event['type'] == 'compaction/summary' else ('content',) if event['type'] == 'tool/ptc-dispatch' else ()
    for key in fields:
        if key == 'rawOutput' and data.get(key, UNDEFINED) is UNDEFINED:
            continue
        original = data.get(key, UNDEFINED)
        content = migrateV3Content(original, subject + '.' + key)
        if content is not original:
            data = dict(data, **{key: content})
    if event['type'] == 'team/message/queued' and isinstance(data.get('message'), dict):
        message = _message(data['message'], subject)
        if message is not data['message']:
            data = dict(data, message=message)
    if event['type'] == 'request/header' and isinstance(data.get('header'), dict):
        tools = data['header'].get('tools')
        if isinstance(tools, list):
            for index, tool in enumerate(tools):
                if isinstance(tool, dict) and 'deferLoading' in tool:
                    raise SessionFormatUnsupportedMigrationError(
                        '{}.header.tools[{}] contains deferLoading, which is only defined in V4'.format(subject, index))
    if event['type'] in ('assistant/message', 'assistant/attempt') and isinstance(data.get('stream'), list):
        stream = data['stream']
        converted = []
        for index, entry in enumerate(stream):
            item = entry
            if isinstance(entry, dict) and entry.get('type') == 'chunk':
                original = entry.get('chunk', UNDEFINED)
                chunk = _chunk(original, '{}.stream[{}]'.format(subject, index))
                if chunk is not original:
                    item = dict(entry, chunk=chunk)
            converted.append(item)
        if any(a is not b for a, b in zip(converted, stream)):
            data = dict(data, stream=converted)
    return mapped if data is original_data else dict(mapped, data=data)
