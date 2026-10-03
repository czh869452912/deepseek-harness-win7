import base64
import json
import math
import os
import re


MAX_SAFE_INTEGER = 9007199254740991


def safe_integer(value):
    return (type(value) in (int, float) and 0 <= value <= MAX_SAFE_INTEGER
            and math.isfinite(value) and value == int(value))


def resolve_page_size(value):
    if not safe_integer(value) or value < 1:
        raise ValueError('acp: sessionListPageSize must be a positive safe integer')
    return int(value)


def encode_cursor(created_at, session_id):
    encoded = json.dumps([int(created_at), session_id], ensure_ascii=False, separators=(',', ':'))
    encoded = re.sub('[\ud800-\udfff]', lambda match: '\\u%04x' % ord(match.group()), encoded)
    return base64.urlsafe_b64encode(encoded.encode('utf-8')).decode('ascii').rstrip('=')


def decode_cursor(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]+', value):
            raise ValueError()
        decoded = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)).decode('utf-8'))
        if (not isinstance(decoded, list) or len(decoded) != 2 or not safe_integer(decoded[0])
                or not isinstance(decoded[1], str) or not decoded[1]):
            raise ValueError()
        if encode_cursor(decoded[0], decoded[1]) != value:
            raise ValueError()
        return int(decoded[0]), decoded[1]
    except (ValueError, UnicodeError, OverflowError):
        raise ValueError('session/list cursor is invalid') from None


def utf8_key(value):
    return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def same_directory(left, right):
    if left is None:
        return False
    try:
        if os.path.exists(left) and os.path.exists(right):
            return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        pass
    return os.path.abspath(left) == os.path.abspath(right)


def field(header, name):
    return header.get(name) if isinstance(header, dict) else getattr(header, name, None)
