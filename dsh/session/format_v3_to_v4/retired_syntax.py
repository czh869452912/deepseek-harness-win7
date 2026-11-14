"""Reject retired interpreted syntax while leaving extension payloads opaque."""
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError


def _block(block, subject):
    if isinstance(block, dict) and block.get('type') == 'tool-result':
        raise SessionFormatError(subject + ' must not contain a released tool-result wrapper')


def _content(value, subject):
    if isinstance(value, list):
        for block in value:
            _block(block, subject)


def _message(value, subject):
    if isinstance(value, dict):
        _content(value.get('content'), subject)


def assertV4RetiredSyntax(row):
    if not isinstance(row, dict):
        return
    kind = row.get('type')
    if kind in ('tool/code-dispatch-start', 'tool/code-dispatch') and row.get('ignorable') is not True:
        raise SessionFormatUnsupportedMigrationError('format v4 rejects retired event type ' + kind)
    data = row.get('data')
    if kind == 'request/header':
        if not isinstance(data, dict) or not isinstance(data.get('header'), dict):
            raise SessionFormatError('format v4 request/header requires data and header objects')
        if 'system' in data['header']:
            raise SessionFormatError('format v4 request/header rejects retired header.system')
        return
    if not isinstance(data, dict):
        return
    # JavaScript String(undefined/null/bool) must survive diagnostics unchanged.
    from dsh.core.session.json import UNDEFINED
    from dsh.session.format_v2_to_v3.payload import display
    subject = 'format v4 {} at seq {} content'.format(display(row.get('type', UNDEFINED)), display(row.get('seq', UNDEFINED)))
    if kind == 'user/message':
        _content(data.get('content'), subject)
    elif kind in ('developer/message', 'assistant/message', 'team/message/queued'):
        _message(data.get('message'), subject)
    elif kind in ('agent/inbox/spliced', 'session/title-llm-request'):
        messages = data.get('inserted' if kind == 'agent/inbox/spliced' else 'messages')
        if isinstance(messages, list):
            for message in messages:
                _message(message, subject)
    elif kind == 'compaction/summary':
        _content(data.get('summary'), subject)
        _content(data.get('rawOutput'), subject)
    elif kind == 'tool/ptc-dispatch':
        _content(data.get('content'), subject)
    if kind in ('assistant/message', 'assistant/attempt') and isinstance(data.get('stream'), list):
        for entry in data['stream']:
            if not isinstance(entry, dict) or entry.get('type') != 'chunk':
                continue
            chunk = entry.get('chunk')
            if not isinstance(chunk, dict):
                continue
            if chunk.get('type') == 'block-end':
                _block(chunk.get('block'), subject)
            if chunk.get('type') == 'block-start' and chunk.get('blockType') == 'tool-result':
                raise SessionFormatError(subject + ' must not contain a released tool-result wrapper')
