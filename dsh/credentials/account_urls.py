"""Restricted Platform origins and browser destinations, with special-URL normalization."""
import re

from dsh.credentials.account_errors import PlatformAuthError
from dsh.host.url_current import InvalidUrlError, _url

_PORT = re.compile(r'http://(?:localhost|127\.0\.0\.1|\[::1\]):([0-9]+)/?', re.I | re.ASCII)


def platformOrigin(value, allowLoopbackHttp, field):
    url = _url(value)
    if (url['credentials'] or url['pathname'] != '/' or url['search'] or url['hash'] or
        not (url['protocol'] == 'https:' or (allowLoopbackHttp and url['hostname'] in
             ('localhost', '127.0.0.1', '[::1]') and url['protocol'] == 'http:'))):
        raise ValueError('account: '+field+' must be an HTTPS origin or explicitly enabled loopback HTTP origin')
    return url['origin']


def browserUrl(value, origin, path, rewriteOrigin=False):
    from dsh.credentials.account_protocol import _diagnostic
    try:
        url = _url(value)
    except (ValueError, UnicodeError):
        _diagnostic('browser URL rejected', dict(path=path, reason='invalid-url'))
        raise PlatformAuthError('protocol')
    allowed = url['origin'] == origin or (rewriteOrigin and url['protocol'] == 'https:')
    if not allowed or url['pathname'] != path or url['credentials'] or url['hash']:
        _diagnostic('browser URL rejected', dict(path=path, originMismatch=not allowed,
                    pathMismatch=url['pathname'] != path, hasCredentials=url['credentials'], hasFragment=bool(url['hash'])))
        raise PlatformAuthError('protocol')
    return origin+url['pathname']+url['search'] if rewriteOrigin else url['href']


def loginOrigin(value):
    try:
        url = _url(value)
    except (ValueError, UnicodeError):
        raise PlatformAuthError('protocol')
    match = _PORT.fullmatch(value)
    if (match is None or int(match.group(1)) == 0 or url['protocol'] != 'http:' or
        url['hostname'] not in ('localhost', '127.0.0.1', '[::1]') or url['credentials'] or
        url['pathname'] != '/' or url['search'] or url['hash']):
        raise PlatformAuthError('protocol')
    return 'http://'+url['hostname']+':'+str(int(match.group(1)))
