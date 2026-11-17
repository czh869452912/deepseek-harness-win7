"""Run pinned SDK request/option validation, with closed native path queries."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from dsh.cordis.utils import _UNDEFINED
from dsh.javascript.runtime import JavaScriptRuntimeError, encode, verify_resources, worker_environment
from .errors import OfficeKitError
from .font_discovery import system_font_directories

RESOURCES = Path(__file__).with_name('contract_runtime')
MANIFEST_SHA256 = '7f21ab9e2e7d5cbb1ccf8314dbdba9a4f4ba9eebb0cf086023fde12e579f4c42'


def bootstrap():
    raw = (RESOURCES / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('Office contracts manifest differs.')
    manifest = json.loads(raw)
    if manifest['format'] != 'dsh-office-contracts@1' or manifest['target_upstream'] != '38a6a5c965aa99ab525161efb7cc5cf1fe62fced':
        raise JavaScriptRuntimeError('Office contracts Source differs.')
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name or hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('Office contracts resource differs.')
    return '\n'.join((RESOURCES / name).read_text(encoding='utf-8') for name in ('contracts.js', 'driver.js'))


def _cache_directory():
    home = os.path.expanduser('~')
    if os.name == 'nt':
        return os.path.normpath(os.path.join(os.environ.get('LOCALAPPDATA', os.path.join(home, 'AppData/Local')), 'libreoffice-kit/Cache'))
    import sys
    if sys.platform == 'darwin':
        return os.path.join(home, 'Library/Caches/libreoffice-kit')
    cache = os.environ.get('XDG_CACHE_HOME', '')
    return os.path.join(cache if os.path.isabs(cache) else os.path.join(home, '.cache'), 'libreoffice-kit')


def prepare(kind, value):
    paths = {}
    def register(path):
        if not isinstance(path, str) or path in paths:
            return
        try:
            resolved = os.path.abspath(path)
        except (ValueError, OSError):
            resolved = path  # NUL paths are rejected by the original validator.
        paths[path] = dict(absolute=os.path.isabs(path), resolved=resolved, extension=os.path.splitext(path)[1])
        if resolved not in paths:
            paths[resolved] = dict(absolute=os.path.isabs(resolved), resolved=resolved, extension=os.path.splitext(resolved)[1])
    if isinstance(value, dict):
        for key in ('inputPath', 'outputPath', 'outputDir', 'fontMetadataCacheDirectory'):
            register(value.get(key))
    cache_directory = _cache_directory()
    register(cache_directory)
    request = dict(kind=kind, value=value, paths=paths, systemRoots=system_font_directories(), cacheDirectory=cache_directory, specials=[])
    if kind == 'images' and isinstance(value, dict) and all(isinstance(value.get(key), str) for key in ('inputPath', 'outputDir')):
        source, output = (paths[value[key]]['resolved'] for key in ('inputPath', 'outputDir'))
        try:
            within = os.path.relpath(source, output)
        except (ValueError, OSError):
            within = source
        request.update(resolvedInput=source, resolvedOutput=output, within=within)
        register(within)
    def clean(item, path):
        if item is _UNDEFINED or isinstance(item, float) and not math.isfinite(item):
            kind = 'undefined' if item is _UNDEFINED else 'nan' if math.isnan(item) else 'positive' if item > 0 else 'negative'
            request['specials'].append(dict(path=path, kind=kind))
            return None
        if isinstance(item, dict):
            return {key: clean(child, path + [key]) for key, child in item.items()}
        if isinstance(item, list):
            return [clean(child, path + [index]) for index, child in enumerate(item)]
        return item
    request['value'] = clean(value, ['value'])
    return request


def observe(operations):
    request = dict(body='return null', name='office-contracts', timeoutMs=10000,
                   bootstrap=bootstrap(), operations=[prepare(kind, value) for kind, value in operations])
    result = subprocess.run([str(verify_resources())], input=encode(request) + encode(dict(type='go')),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(), timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        frames = [json.loads(line.decode('utf-8')) for line in result.stdout.splitlines()]
    except (UnicodeError, ValueError):
        frames = []
    if result.returncode or len(frames) != 2 or frames[0] != dict(type='ready') or frames[1].get('type') != 'terminal' or len(frames[1].get('result', [])) != len(operations):
        raise JavaScriptRuntimeError('Office contract worker failed: ' + result.stderr.decode('utf-8', 'replace')[-1200:])
    return frames[1]['result']


def resolve_request(kind, value):
    row = observe([(kind, value)])[0]
    if row['ok']:
        return row['value']
    if 'code' in row:
        raise OfficeKitError(row['code'], row['message'])
    error = TypeError(row['message']) if row['name'] == 'TypeError' else ValueError(row['message'])
    error.name = row['name']
    raise error
