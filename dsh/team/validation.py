"""Team text and advisory workspace-prefix normalization."""
import json
import re
from dsh.team.errors import TeamError

JS_WHITESPACE='\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def required_text(value,field,max_length):
    text=value.strip(JS_WHITESPACE)
    if not text:
        raise TeamError(field+' must be non-empty','TEAM_INVALID_ARGUMENT')
    if len(text.encode('utf-16-le','surrogatepass'))//2>max_length:
        raise TeamError('%s exceeds %s characters' % (field,max_length),'TEAM_INVALID_ARGUMENT')
    return text


def write_scope(value):
    normalized=value.replace('\\','/')
    if normalized.startswith('./'):normalized=normalized[2:]
    normalized=normalized.rstrip('/')
    if (not normalized or normalized.startswith('/') or re.match(r'^[a-z]:',normalized,re.I)
            or any(part in ('','.','..') for part in normalized.split('/'))):
        raise TeamError('invalid workspace-relative write scope '+json.dumps(value,ensure_ascii=False,separators=(',',':')),
                        'TEAM_INVALID_WRITE_SCOPE')
    return normalized
