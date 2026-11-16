"""Registry retry boundaries and published-version facts; no network effects."""
import re
from urllib.parse import quote, urlsplit

from dsh.boot.plugin_install_spec import _url_host
from dsh.boot.semver import parse
from dsh.cordis.utils import _js_own_enumerable_keys

OFFICIAL_NPM_REGISTRY = 'https://registry.npmjs.org/'
NPMMIRROR_REGISTRY = 'https://registry.npmmirror.com/'
UNSPECIFIED = object()
VERSION_LIST_FIELDS = ['versions', 'time', 'dist-tags']
VERSION_FIELDS = ['name', 'version', 'engines', 'peerDependencies', 'deprecated', 'dsh']


def normalize_registry(url):
    try:
        text = url.strip(''.join(chr(n) for n in range(33))).replace('\t', '').replace('\n', '').replace('\r', '')
        match = re.match(r'^(https?):', text, re.I)
        if match is None:raise ValueError()
        protocol = match.group(1).lower()
        rest = text[match.end():]
        delimiter = min([rest.find(c) for c in '?#' if c in rest] or [len(rest)])
        rest = rest[:delimiter].replace('\\', '/')+rest[delimiter:]
        normalized = protocol+'://'+rest.lstrip('/')
        fields = urlsplit(normalized)
        host = _url_host(normalized)
        if not host:raise ValueError()
        userinfo = fields.netloc.rsplit('@', 1)[0] if '@' in fields.netloc else ''
        authority = host
        if userinfo:
            user, separator, password = userinfo.partition(':')
            safe = "!$&'()*+,-._~%"
            credentials = quote(user, safe=safe)
            if separator and password:credentials += ':'+quote(password, safe=safe)
            if credentials:authority = credentials+'@'+host
        path = fields.path or '/'
        segments = []
        for index, segment in enumerate(path.split('/')):
            dot = re.sub('%2e', '.', segment, flags=re.I)
            last = index == len(path.split('/'))-1
            if dot == '.':
                if last:segments.append('')
            elif dot == '..':
                if len(segments) > 1:segments.pop()
                if last:segments.append('')
            else:segments.append(segment)
        path = '/'.join(segments)
        if not path.endswith('/'):path += '/'
        def encoded(value, forbidden):
            return quote(value, safe=''.join(chr(n) for n in range(33, 127) if chr(n) not in forbidden))
        result = protocol+'://'+authority+encoded(path, '"#<>?`{}')
        if '?' in normalized.split('#', 1)[0]:result += '?'+encoded(fields.query, '"#<>\'')
        if '#' in normalized:result += '#'+encoded(fields.fragment, '"<>`')
        return result
    except (ValueError, TypeError, AttributeError):
        raise ValueError('a registry must be an http(s) URL: '+str(url))


def registry_plan(requested, configured):
    own = None if configured['resolved'] is None else normalize_registry(configured['resolved'])
    fallbacks = [normalize_registry(url) for url in configured['fallbackRegistries']]
    public = own is not None and (own == OFFICIAL_NPM_REGISTRY or own in fallbacks)
    def key(registry):return own if registry is None else normalize_registry(registry)
    known, keys = [], []
    for registry in [configured['registry']]+configured['fallbackRegistries']:
        if registry is None and not public:continue
        identity = key(registry)
        if identity in keys:continue
        known.append(None if registry is None else normalize_registry(registry))
        keys.append(identity)
    first = configured['registry'] if requested is UNSPECIFIED else requested
    identity = key(first)
    normalized = None if first is None else normalize_registry(first)
    if ((first is None or identity == own) and not public) or identity not in keys:return [normalized]
    return [normalized]+[registry for registry, other in zip(known, keys) if other != identity]


_ERROR_LINE = re.compile(r'ERR_|ERROR|\berror\b|fatal:|Could not resolve|unable to access|ssh:|\bE[A-Z]{4,}\b', re.ASCII)


def attribute_failure(kind, log, spec):
    if kind not in ('network', 'timeout', 'not-found', 'no-matching-version'):return 'other'
    host = spec.get('host') if spec['kind'] in ('git', 'tarball') else None
    if host is None:return 'registry'
    return 'spec-host' if any(_ERROR_LINE.search(line) and host.lower() in line.lower() for line in log.split('\n')) else 'registry'


def newer_versions(answer, installed):
    fields = answer if isinstance(answer, dict) else {}
    listed = fields.get('versions')
    if isinstance(listed, str):listed = [listed]
    if not isinstance(listed, list):raise ValueError('pnpm view answered no versions')
    time = fields.get('time') if isinstance(fields.get('time'), dict) else {}
    tags = fields.get('dist-tags') if isinstance(fields.get('dist-tags'), dict) else {}
    selected = []
    for version in listed:
        try:parsed = parse(version)
        except ValueError:continue
        if parsed > parse(installed):selected.append((version, parsed))
    selected.sort(key=lambda row:row[1], reverse=True)
    result = []
    for version, parsed in selected:
        item = dict(version=version, tags=[tag for tag in _js_own_enumerable_keys(tags) if tags[tag] == version], prerelease=parsed.pre is not None)
        if isinstance(time.get(version), str):item['publishedAt'] = time[version]
        result.append(item)
    return result


def version_facts(answer, name, version):
    fields = answer if isinstance(answer, dict) else {}
    manifest = dict(name=fields['name'] if isinstance(fields.get('name'), str) else name,
                    version=fields['version'] if isinstance(fields.get('version'), str) else version)
    for field in ('engines', 'peerDependencies'):
        if field in fields:manifest[field] = fields[field]
    result = dict(manifest=manifest, bundle=isinstance(fields.get('dsh'), dict) and isinstance(fields['dsh'].get('bundle'), dict))
    if isinstance(fields.get('deprecated'), str) and fields['deprecated'] != '':result['deprecated'] = fields['deprecated']
    return result
