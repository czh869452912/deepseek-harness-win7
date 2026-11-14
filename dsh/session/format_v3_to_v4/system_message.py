"""Validate native system message fields before suffix recovery can discard them."""
from dsh.core.session.json import UNDEFINED
from dsh.session.format import SessionFormatError, sessionFormatCount


def _record(value, subject):
    if not isinstance(value, dict):
        raise SessionFormatError('format v4 ' + subject + ' requires an object')
    return value


def _string(value, subject, nonempty=False):
    if not isinstance(value, str) or nonempty and not value:
        raise SessionFormatError('format v4 ' + subject + ' requires a string' + (' with content' if nonempty else ''))


def _positive(value, subject):
    if sessionFormatCount(value, subject) == 0:
        raise SessionFormatError('format v4 ' + subject + ' must be positive')


def _image(value):
    attachment = _record(value, 'system image attachment')
    _string(attachment.get('attachmentId'), 'system image attachmentId', True)
    if attachment.get('mediaType') not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
        raise SessionFormatError('format v4 system image requires a supported mediaType')
    sessionFormatCount(attachment.get('bytes', UNDEFINED), 'system image bytes')
    _positive(attachment.get('width', UNDEFINED), 'system image width')
    _positive(attachment.get('height', UNDEFINED), 'system image height')
    if attachment.get('name', UNDEFINED) is not UNDEFINED:
        _string(attachment['name'], 'system image name')
    if attachment.get('originalDimensions', UNDEFINED) is not UNDEFINED:
        original = _record(attachment['originalDimensions'], 'system image originalDimensions')
        _positive(original.get('width', UNDEFINED), 'system image original width')
        _positive(original.get('height', UNDEFINED), 'system image original height')


def assertV4SystemMessageFields(row):
    if not isinstance(row, dict) or row.get('type') != 'system/message':
        return
    data = _record(row.get('data'), 'system/message data')
    _positive(data.get('turn', UNDEFINED), 'system/message turn')
    _positive(data.get('step', UNDEFINED), 'system/message step')
    message = _record(data.get('message'), 'system message')
    _string(message.get('id'), 'system message id', True)
    if message.get('role') != 'system':
        raise SessionFormatError('format v4 system message requires system role')
    content = message.get('content')
    if not isinstance(content, list):
        raise SessionFormatError('format v4 system message requires content array')
    for value in content:
        block = _record(value, 'system content block')
        _string(block.get('type'), 'system content type', True)
        kind = block['type']
        if kind in ('text', 'reasoning'):
            _string(block.get('text'), 'system content text')
        elif kind == 'tool-call':
            _string(block.get('id'), 'system tool-call id', True)
            _string(block.get('name'), 'system tool-call name', True)
            _string(block.get('arguments'), 'system tool-call arguments')
        elif kind == 'image':
            _image(block.get('attachment'))
        elif kind == 'tool-result':
            raise SessionFormatError('format v4 system content rejects retired tool-result wrappers')
