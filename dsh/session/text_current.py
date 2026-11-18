"""Current first-party semantic extraction; legacy nested results stay legacy."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re

from dsh.session.session_query import SessionQueryError, _join_text
from dsh.session.text import literal_pattern, read_fold_classes, trim_text

CASE_FOLDING_SHA256 = '6f1f9c588eb4a5c718d9e8f93b782685e5c7fec872cf05e8e6878053599e09bb'


def verify_case_folding(path=None):
    path = Path(path) if path is not None else Path(__file__).parent / 'bin/unicode/CaseFolding-16.0.0.txt'
    if hashlib.sha256(path.read_bytes()).hexdigest() != CASE_FOLDING_SHA256:
        raise RuntimeError('Pinned current Unicode case-folding data differs')
    return path


@lru_cache(maxsize=1)
def fold_classes():
    return read_fold_classes(verify_case_folding())


def compile_session_text_filter(text):
    trimmed = trim_text(text)
    if not trimmed:
        raise SessionQueryError('session text filter must contain non-whitespace text', 'SESSION_QUERY_INVALID_FILTER')
    return re.compile(literal_pattern(trimmed, fold_classes()))


def content_text(content):
    parts = []
    for block in content:
        if block['type'] == 'text':
            parts.append(block['text'])
        elif block['type'] == 'tool-call':
            parts.extend((block['name'], block['arguments']))
    return _join_text(parts)


def extract_session_event_text(event):
    kind = event['type']
    if kind not in ('user/message', 'assistant/message', 'tool/call', 'tool/result', 'todo/write', 'turn/end'):
        return ''
    data = event['data']
    if kind == 'user/message':
        return content_text(data['content'])
    if kind == 'assistant/message':
        return content_text(data['message']['content'])
    if kind == 'tool/call':
        return _join_text([data['name'], data['arguments']])
    if kind == 'tool/result':
        error = data.get('error') or {}
        return _join_text([content_text(data['message']['content']), error.get('name', ''), error.get('code', '')])
    if kind == 'todo/write':
        return _join_text([part for todo in data['todos'] for part in (todo['status'], todo['content'])])
    reason = data['reason']
    if reason['kind'] == 'error':
        return _join_text(['error', reason['error']['message']])
    return reason['kind'] if reason['kind'] in ('aborted', 'max-tokens', 'interrupted') else ''
