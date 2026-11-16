"""Special URL normalization shared by native HTTP request carriers."""
import re
from urllib.parse import quote, urlsplit
from dsh.host.http_proxy_policy import parse_url

_C0 = ''.join(chr(index) for index in range(33))


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
    if scheme == 'file':
        try:
            file_url = urlsplit(text.replace('\\', '/'))
            if file_url.username is not None or file_url.password is not None or file_url.port is not None:
                raise ValueError('invalid file authority')
        except ValueError:
            raise InvalidUrlError()
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
