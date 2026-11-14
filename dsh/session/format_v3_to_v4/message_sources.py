"""Native producer-source refusal before recoverable physical-row decoding."""
from dsh.session.format import SessionFormatError
from .sources import mapEventMessages


def _source(message):
    value = message.get('source')
    if not isinstance(value, dict) or not isinstance(value.get('kind'), str) or not value['kind'] or value['kind'] == 'plugin':
        raise SessionFormatError('format v4 message requires a producer-owned source kind')
    return message


def assertV4MessageSources(event):
    mapEventMessages(event, _source)


def assertV4SourceRowAdmission(row):
    if not isinstance(row, dict) or not isinstance(row.get('data'), dict):
        return
    kind, data = row.get('type'), row['data']
    messages = [data] if kind == 'user/message' else [data.get('message')] if kind in (
        'system/message', 'assistant/message', 'tool/result') else data.get('inserted') if kind == 'agent/inbox/spliced' else data.get('messages') if kind == 'session/title-llm-request' else []
    if not isinstance(messages, list):
        return
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get('source'), dict) and message['source'].get('kind') == 'plugin':
            _source(message)
