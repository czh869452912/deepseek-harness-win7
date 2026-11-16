"""Restricted Platform origins and browser destinations, with special-URL normalization."""
import re
from urllib.parse import quote, urlsplit

from dsh.credentials.account_errors import PlatformAuthError
from dsh.host.http_proxy_policy import parse_url

_C0 = ''.join(chr(index) for index in range(33))
_PORT = re.compile(r'http://(?:localhost|127\.0\.0\.1|\[::1\]):([0-9]+)/?', re.I | re.ASCII)


class InvalidUrlError(ValueError):
    code = 'ERR_INVALID_URL'

    def __init__(self):
        super().__init__('Invalid URL')


def _encode(value, forbidden):
    # URL uses a USVString, replacing unpaired UTF-16 surrogates before UTF-8.
    value = value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')
    safe = ''.join(chr(index) for index in range(33, 127) if chr(index) not in forbidden)
    return quote(value, safe=safe, encoding='utf-8')


def _url(value):
    text = value.strip(_C0).replace('\t', '').replace('\r', '').replace('\n', '')
    match = re.match(r'^([A-Za-z][A-Za-z0-9+.-]*):', text)
    if match is None:
        raise InvalidUrlError()
    scheme = match.group(1).lower()
    if scheme not in ('http', 'https', 'ftp', 'ws', 'wss', 'file'):
        return dict(protocol=scheme+':', origin='null', pathname='', search='', hash='', credentials=False, href=text, hostname='')
    parsed_host = parse_url(text)
    if parsed_host is None:
        if scheme == 'file':
            return dict(protocol='file:', origin='null', pathname='/', search='', hash='', credentials=False, href=text, hostname='')
        raise InvalidUrlError()
    rest = text[match.end():].replace('\\', '/')
    split = urlsplit(scheme+'://'+rest.lstrip('/'))
    hostname = parsed_host['hostname']
    if ':' in hostname:
        hostname = '['+hostname+']'
    default = 443 if scheme in ('https', 'wss') else 80 if scheme in ('http', 'ws') else 21
    port = parsed_host['port']
    authority = hostname+(':'+str(port) if port != default and port is not None else '')
    origin = scheme+'://'+authority if scheme != 'file' else 'null'
    segments = []
    parts = (split.path or '/').split('/')[1:]
    for index, part in enumerate(parts):
        dotted = re.sub('%2e', '.', part, flags=re.I)
        if dotted in ('.', '..'):
            if dotted == '..' and segments:
                segments.pop()
            if index == len(parts)-1:
                segments.append('')
        else:
            segments.append(_encode(part, '"#<>?`{}'))
    path = '/'+'/'.join(segments)
    search = '?'+_encode(split.query, '"#<>\'') if split.query else ''
    fragment = '#'+_encode(split.fragment, '"<>`') if split.fragment else ''
    # Empty ?/# are retained by href, but absent from URL.search / URL.hash.
    suffix = (search or ('?' if '?' in text.split('#', 1)[0] else ''))+(fragment or ('#' if '#' in text else ''))
    return dict(protocol=scheme+':', origin=origin, pathname=path, search=search, hash=fragment,
                credentials=bool(split.username or split.password), hostname=hostname, href=scheme+'://'+authority+path+suffix)


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
