"""Plugin detail documents and images shared by Host readers."""
import json
import os
import posixpath
import re
import stat
from urllib.parse import unquote, quote

from dsh.core.abort import NEVER_ABORTED
from dsh.core.session.json import UNDEFINED
from dsh.host.http_proxy_policy import JS_SPACE

README_NAMES = ['README.md', 'readme.md', 'Readme.md', 'README.markdown', 'README']
NPM_FILE_SOURCES = ['jsdelivr', 'unpkg', 'npmmirror']


class DetailFailure(RuntimeError):
    name = 'DetailFailure'
    def __init__(self, reason, message):
        self.reason, self.message = reason, message
        super().__init__(message)


def join_path(directory, name):return name if directory == '' else directory+'/'+name


def readme_name(names):
    matches = [name for name in names if re.fullmatch(r'readme(?:\.md|\.markdown)?', name, re.I | re.ASCII)]
    def rank(name):return (README_NAMES.index(name) if name in README_NAMES else len(README_NAMES), name.encode('utf-16-be', errors='surrogatepass'))
    return min(matches, key=rank) if matches else None


def language_chain(language):
    identity = language.lower()
    if not re.fullmatch(r'[a-z]{2,8}(?:-[a-z0-9]{1,8})*', identity):raise ValueError('Not a language id: '+language)
    parts = identity.split('-')
    return list(dict.fromkeys(['-'.join(parts[:len(parts)-index]) for index in range(len(parts))]+['en']))


def detail_path(value=UNDEFINED, label='meta.detail'):
    if value is UNDEFINED:return None
    def invalid(rule):return DetailFailure('invalid', label+' '+rule)
    if not isinstance(value, str) or not value.strip(JS_SPACE):raise invalid('must be a non-empty string')
    if '\\' in value or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value) or any(part in ('', '.', '..') for part in value.split('/')):
        raise invalid('must be a relative path inside the package')
    if not re.search(r'\.(?:md|markdown)\Z', value, re.I | re.ASCII):raise invalid('must name a Markdown file')
    return value


def markdown_of(data):
    # TextDecoder consumes one UTF-8 BOM; the original also removes one FEFF.
    text = data.decode('utf-8-sig', errors='replace')
    if text.startswith('\ufeff'):text = text[1:]
    return re.sub(r'^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)', '', text, count=1)


async def read_package_document(files, directory, languages, max_bytes, signal=NEVER_ABORTED):
    detail = None
    for language in languages:
        names = list(dict.fromkeys([language, re.sub(r'^([a-z]{2,3})-([a-z]{2})$', lambda m:m[1]+'-'+m[2].upper(), language)]))
        for name in names:
            path = join_path(directory, 'locale/'+name+'.json')
            data = await files.read(path, max_bytes, signal)
            if data is None:continue
            try:
                value = json.loads(data.decode('utf-8-sig', errors='replace'), parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Invalid JSON constant '+value)))
            except (ValueError, UnicodeError) as error:raise DetailFailure('invalid', path+': '+str(error))
            meta = value.get('meta') if isinstance(value, dict) else None
            detail = detail_path(meta.get('detail', UNDEFINED) if isinstance(meta, dict) else UNDEFINED, path+': meta.detail')
            break
        if detail is not None:break
    if detail is not None:
        path = join_path(directory, detail)
        data = await files.read(path, max_bytes, signal)
        if data is None:raise DetailFailure('invalid', path+', named by meta.detail, does not exist')
        return dict(origin='locale', path=path, markdown=markdown_of(data))
    readme = await files.readme(directory, max_bytes, signal)
    return None if readme is None else dict(origin='readme', path=readme['path'], markdown=markdown_of(readme['bytes']))


_IMAGE_TYPES = dict(png='image/png', jpg='image/jpeg', jpeg='image/jpeg', gif='image/gif', webp='image/webp', avif='image/avif', svg='image/svg+xml')


def detail_image(document, authored):
    try:
        value = re.split(r'[?#]', authored, maxsplit=1)[0]
        if re.search(r'%(?![0-9a-fA-F]{2})', value):return None
        decoded = unquote(value, encoding='utf-8', errors='strict')
        decoded.encode('utf-8', errors='strict')
    except (UnicodeError, ValueError):return None
    if '\\' in decoded or '\0' in decoded:return None
    path = posixpath.normpath(decoded[1:] if decoded.startswith('/') else posixpath.join(posixpath.dirname(document), decoded))
    # Node posix.normalize collapses all repeated leading slashes to one.
    if path in ('.', '..') or path.startswith('../') or posixpath.isabs(path):return None
    media = _IMAGE_TYPES.get(posixpath.splitext(path)[1][1:].lower())
    if decoded.endswith('/') and path != '.':path += '/'
    return None if media is None else dict(path=path, mediaType=media)


async def readme_by_name(read, directory, max_bytes, signal=NEVER_ABORTED, names=README_NAMES):
    for name in names:
        path = join_path(directory, name)
        data = await read(path, max_bytes, signal)
        if data is not None:return dict(path=path, bytes=data)
    return None


class LocalFiles:
    def __init__(self, root, revision):
        self.root, self.key = root, 'local:'+root+'@'+revision

    async def read(self, path, max_bytes, signal=NEVER_ABORTED):
        try:
            base = os.path.realpath(self.root)
            file = os.path.realpath(os.path.join(base, *path.split('/')))
            inside = os.path.relpath(file, base)
            if inside in ('.', '..') or inside.startswith('..'+os.sep):return None
            info = os.lstat(file)
            if not stat.S_ISREG(info.st_mode):return None
            if info.st_size > max_bytes:raise DetailFailure('too-large', path+' exceeds '+str(max_bytes)+' bytes')
        except (OSError, ValueError):return None
        with open(file, 'rb') as stream:data = stream.read()
        if len(data) > max_bytes:raise DetailFailure('too-large', path+' exceeds '+str(max_bytes)+' bytes')
        return data

    async def readme(self, directory, max_bytes, signal=NEVER_ABORTED):
        try:
            with os.scandir(os.path.join(self.root, *directory.split('/'))) as entries:
                names = [entry.name for entry in entries if entry.is_file(follow_symlinks=False) or entry.is_symlink()]
        except OSError:return None
        name = readme_name(names)
        if name is None:return None
        path = join_path(directory, name)
        data = await self.read(path, max_bytes, signal)
        return None if data is None else dict(path=path, bytes=data)


def npm_file_source_order(configured, preferred=()):
    first = sorted([source for source in configured if source in preferred], key=preferred.index)
    return first+[source for source in configured if source not in first]


def encode_path(path):return '/'.join(quote(segment, safe="~!*'()-._") for segment in path.split('/'))


def detail_image_response(outcome, cache_control):
    statuses = {'too-large':413, 'network':502, 'denied':403, 'git-unavailable':503, 'invalid':400}
    if isinstance(outcome, dict):status, body, media = 200, bytes(outcome['bytes']), outcome['mediaType']
    else:status, body, media = (404, 'not found', None) if outcome is None else (statuses[outcome], outcome, None)
    return dict(status=status, body=body, headers={'Content-Type':media or 'text/plain; charset=utf-8',
        'Cache-Control':cache_control if status == 200 else 'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'"})
