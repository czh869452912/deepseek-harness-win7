"""Validated initialization and exchange payloads; never log their values."""
import math
import re

from dsh.credentials.account_errors import PlatformAuthError
from dsh.credentials.account_urls import _url


def _isUrl(value):
    if not isinstance(value, str):
        return False
    try:
        _url(value)
        return True
    except (ValueError, UnicodeError):
        return False


def payloadIssues(kind, value):
    if not isinstance(value, dict):
        return [dict(path=[], code='invalid_type')]
    issues = []
    fields = ('authorize_url', 'authorize_id', 'expires_in') if kind == 'initialization' else ('token', 'authorized_url')
    for field in fields:
        item = value.get(field)
        code = None
        if field == 'expires_in':
            if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
                code = 'invalid_type'
            elif item <= 0:
                code = 'too_small'
        elif not isinstance(item, str):
            code = 'invalid_type'
        elif field in ('authorize_url', 'authorized_url'):
            if not _isUrl(item):
                code = 'invalid_format'
        elif field == 'authorize_id':
            if not item:
                code = 'too_small'
        elif re.fullmatch('[\x21-\x7e]+', item) is None:
            code = 'invalid_format'
        if code:
            issues.append(dict(path=[field], code=code))
    return issues


def parsePayload(kind, value):
    if payloadIssues(kind, value):
        raise PlatformAuthError('protocol')
    fields = ('authorize_url', 'authorize_id', 'expires_in') if kind == 'initialization' else ('token', 'authorized_url', 'user')
    return {field: value[field] for field in fields if field in value}
