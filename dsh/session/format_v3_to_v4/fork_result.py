"""Fork-generated not-started result identity and replacement ownership."""
import re

from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError
from dsh.session.format_v2_to_v3.payload import display


def assertV4ForkResult(row):
    if not isinstance(row, dict) or row.get('type') != 'tool/result' or not isinstance(row.get('data'), dict):
        return
    data = row['data']; error, message = data.get('error'), data.get('message')
    if (not isinstance(error, dict) or error.get('code') != 'TOOL_NOT_STARTED' or not isinstance(message, dict)
            or not isinstance(message.get('id'), str) or not message['id'].startswith('forked-tool-result-')):
        return
    source = message.get('source')
    call_id = source.get('callId', UNDEFINED) if isinstance(source, dict) else UNDEFINED
    prefix = 'forked-tool-result-' + display(call_id) + '-'
    suffix = message['id'][len(prefix):]
    operation = row.get('surfaceOp', UNDEFINED)
    replacement = isinstance(operation, dict) and operation.get('op') == 'replace'
    valid_suffix = bool(re.fullmatch(r'(0|[1-9][0-9]*)', suffix))
    sequence = int(suffix) if valid_suffix else -1
    content = message.get('content')
    text = content[0] if isinstance(content, list) and len(content) == 1 else None
    references = row.get('sourceEventSeqs', UNDEFINED)
    seq = row.get('seq', UNDEFINED)
    invalid_position = (type(seq) not in (int, float) or sequence >= seq) if replacement else not _js_strict_equal(sequence, seq)
    invalid_references = (not isinstance(references, list) or len(references) != 1
                          or not _js_strict_equal(references[0], sequence)) if replacement else (references is not UNDEFINED or operation != 'append')
    if (not isinstance(call_id, str) or not message['id'].startswith(prefix) or not valid_suffix
            or sequence > 9007199254740991 or invalid_position or error.get('name') != 'ToolNotStartedError'
            or invalid_references or message.get('role') != 'tool' or message.get('isError') is not True
            or not _js_strict_equal(message.get('toolCallId', UNDEFINED), call_id)
            or not isinstance(source, dict) or source.get('kind') != 'tool'
            or not isinstance(text, dict) or text.get('type') != 'text' or not isinstance(text.get('text'), str)):
        raise SessionFormatError('invalid V4 not-started fork result')
