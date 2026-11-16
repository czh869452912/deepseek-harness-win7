"""Current install identities, pinned Git origins and diagnostic failure kinds."""
import ipaddress
import os
import re
from urllib.parse import urlsplit

from dsh.boot.runtime_resolution import _field
from dsh.host.http_proxy_policy import JS_SPACE, parse_url


_I = re.IGNORECASE | re.ASCII
_SHORTHANDS = dict(github='github.com', gitlab='gitlab.com', bitbucket='bitbucket.org', gist='gist.github.com')
_TARBALL = re.compile(r'\.(?:tgz|tar\.gz)(?:#[^\r\n\u2028\u2029]*)?$', _I)
_PACKAGE = re.compile(r'(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*')


class InvalidInstallSpecError(ValueError):
    name = 'InvalidInstallSpecError'
    def __init__(self, spec, reason):
        self.spec, self.reason = spec, reason
        self.message = 'plugin-manager: '+reason+': '+spec
        super().__init__(self.message)


def _url_host(spec):
    # Python 3.8's urlsplit accepts a bracketed non-IPv6 hostname. WHATWG does not.
    try:
        authority = urlsplit(spec).netloc.rsplit('@', 1)[-1]
        if authority.startswith('['):
            ipaddress.IPv6Address(authority[1:authority.index(']')])
    except (ValueError, IndexError):
        raise TypeError('Invalid URL')
    special = parse_url(spec)
    if special is None:
        raise TypeError('Invalid URL')
    if special['protocol'] in ('http:', 'https:', 'ftp:', 'ws:', 'wss:'):
        host = special['hostname']
        host = '['+host+']' if ':' in host else host
        defaults = {'http:':80, 'https:':443, 'ftp:':21, 'ws:':80, 'wss:':443}
        return host + (':'+str(special['port']) if special['port'] != defaults[special['protocol']] else '')
    # WHATWG keeps opaque-scheme hostname spelling (e.g. ssh/git) intact.
    try:
        parsed = urlsplit(spec)
        port = parsed.port
        host = parsed.netloc.rsplit('@', 1)[-1]
        if host.startswith('['):
            close = host.index(']')
            host = '['+str(ipaddress.IPv6Address(host[1:close]))+']'
        else:
            host = host.split(':', 1)[0]
        if port is not None and not 0 <= port <= 65535:
            raise ValueError('port')
        return host + ('' if port is None else ':'+str(port))
    except (ValueError, IndexError):
        raise TypeError('Invalid URL')


def _git_host(spec):
    shorthand = re.match(r'^([a-z]+):', spec, _I)
    if shorthand and shorthand.group(1).lower() in _SHORTHANDS:
        return _SHORTHANDS[shorthand.group(1).lower()]
    scp = re.match(r'^git@([^:]+):', spec, _I)
    return scp.group(1).lower() if scp else _url_host(re.sub(r'^git\+', '', spec, flags=_I))


def parse_install_spec(raw):
    spec = raw.strip(JS_SPACE)
    def invalid(reason):
        return InvalidInstallSpecError(spec, reason)
    if not spec:
        raise invalid('the package spec must not be empty')
    path = re.sub(r'^(?:file|link):', '', spec)
    if path != spec or os.path.isabs(path):
        if not os.path.isabs(path):
            raise invalid('a local path must be absolute')
        return dict(kind='tarball' if _TARBALL.search(path) else 'path', spec=spec, path=path)
    if re.match(r'^\.{1,2}(?:[\\/]|$)', spec):
        raise invalid('a local path must be absolute')
    git = (re.match(r'^(?:github|gitlab|bitbucket|gist):', spec, _I)
           or re.match(r'^git(?:\+[a-z]+)?://|^git@[^:]+:', spec, _I)
           or re.match(r'^https?://[^/]+/[^/]+/[^/#]+(?:\.git)?(?:#[^\r\n\u2028\u2029]*)?$', spec, _I))
    if git and not _TARBALL.search(spec):
        return dict(kind='git', spec=spec, host=_git_host(spec))
    if re.match(r'^https?://', spec, _I):
        if _TARBALL.search(spec):
            return dict(kind='tarball', spec=spec, host=_url_host(spec))
        raise invalid('a URL must point at a git repository or a tarball')
    at = spec.find('@', 1)
    name, version = (spec, None) if at < 0 else (spec[:at], spec[at+1:])
    if len(name) > 214 or _PACKAGE.fullmatch(name) is None:
        raise invalid('not a package name the registry accepts')
    if version == '':
        raise invalid('a version after @ must not be empty')
    return dict(kind='registry', spec=spec, name=name, **({} if version is None else dict(range=version)))


def pinned_git_origin(spec):
    try:
        parsed = parse_install_spec(spec)
    except InvalidInstallSpecError:
        return None
    index = parsed['spec'].find('#')
    if parsed['kind'] != 'git' or index < 0:
        return None
    parameters = parsed['spec'][index+1:].split('&')
    paths = [part for part in parameters if part.startswith('path:')]
    others = [part for part in parameters if not part.startswith('path:')]
    if len(paths) > 1 or len(others) != 1 or re.fullmatch(r'[0-9a-f]{40}', ''.join(others), flags=_I) is None:
        return None
    path = (paths[0][5:] if paths else '').strip('/')
    location = re.sub(r'^(github|gitlab|bitbucket|gist):', lambda match:_SHORTHANDS[match.group(1).lower()]+'/', parsed['spec'][:index], flags=_I)
    location = re.sub(r'^git\+', '', location, flags=_I)
    location = re.sub(r'^[a-z][a-z0-9+.-]*://', '', location, flags=_I)
    location = re.sub(r'^[^@/]+@', '', location)
    location = re.sub(r'^([^/:]+):(?!\d)', r'\1/', location)
    location = re.sub(r'\.git$', '', location.rstrip('/'), flags=_I)
    location = re.sub(r'^[^/]+', lambda match:match.group().lower(), location)
    return location+'#'+path


def dependency_spec(name, recorded, profile_dir, package_name=None):
    package_name = name if package_name is None else package_name
    local = re.match(r'^(file|link):(.*)$', recorded, re.DOTALL)
    if local:
        path = re.sub(r'^~(?=$|[\\/])', lambda _:os.path.expanduser('~'), local.group(2))
        spec = local.group(1)+':'+os.path.abspath(os.path.join(profile_dir, path))
    elif re.search(r'^(?!(?:npm|jsr|workspace|catalog):)[a-z][a-z0-9+.-]*:|^[^@/:'+re.escape(JS_SPACE)+r']+@[^:/'+re.escape(JS_SPACE)+r']+:', recorded, flags=_I):
        spec = re.sub(r'^((?:git\+)?https?://)[^/]*@', r'\1', recorded, flags=_I)
    else:
        return name+'@'+recorded
    return spec if package_name == name else name+'@'+spec


_LOG_KINDS = [
    ('build-blocked', re.compile(r'ERR_PNPM_IGNORED_BUILDS|Ignored build scripts|ERR_PNPM_GIT_DEP_PREPARE_NOT_ALLOWED')),
    ('not-found', re.compile(r'ERR_PNPM_FETCH_404|\bE404\b|404 Not Found|Not Found - GET', re.ASCII)),
    ('no-matching-version', re.compile(r'ERR_PNPM_NO_MATCHING_VERSION|\bETARGET\b|No matching version', re.ASCII)),
    ('disk-full', re.compile(r'\bENOSPC\b|no space left on device', _I)),
    ('permission', re.compile(r'\bEACCES\b|\bEPERM\b|permission denied', _I)),
    ('integrity', re.compile(r'ERR_PNPM_TARBALL_INTEGRITY|ERR_PNPM_BAD_TARBALL_SIZE|\bEINTEGRITY\b', re.ASCII)),
    ('unknown', re.compile(r'The requested URL returned error: 40[134]\b', re.ASCII)),
    ('network', re.compile(r'\bENOTFOUND\b|\bECONNRESET\b|\bETIMEDOUT\b|\bECONNREFUSED\b|\bEAI_AGAIN\b|ERR_PNPM_META_FETCH_FAIL|ERR_PNPM_FETCH_5\d\d|ERR_PNPM_FETCH_TIMEOUT|\bFETCH_ERROR\b|socket hang up|Could not resolve host|unable to access', re.ASCII)),
]


def classify_install_failure(facts):
    if facts.get('timedOut') is True:
        return 'timeout'
    if _field(facts.get('cause'), 'code') == 'ENOENT':
        return 'pnpm-missing'
    return next((kind for kind, pattern in _LOG_KINDS if pattern.search(facts['log'])), 'unknown')


parseInstallSpec = parse_install_spec
pinnedGitOrigin = pinned_git_origin
dependencySpec = dependency_spec
classifyInstallFailure = classify_install_failure
