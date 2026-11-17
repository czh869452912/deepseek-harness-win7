"""Read-only package exports/imports resource resolution for the Python host.

Uses the pinned Node 24 ESM condition and target-selection rules. No module is
evaluated, and selected targets are checked before resources are handed to a
consumer. Python package entry execution remains the Loader's responsibility.
"""
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlparse
from dsh.boot.plugin_packages import bare_package_name, _parent, _search_paths, _BUILTINS
from dsh.boot.runtime_resolution import _read

_UNDEFINED = object()
CONDITIONS = frozenset(('node', 'import', 'module-sync', 'node-addons'))
_READS = ContextVar('plugin-resource-resolution-reads', default=None)


@contextmanager
def resolution_read_scope():
    """Share resolver facts only during one synchronous metadata read.

    Node's module resolver reuses its package reader. Keep the Python adapter
    from rereading the same manifests and ancestor paths for every locale,
    while allowing the next metadata call to observe edits and routing changes.
    Resource contents, existence and realpath checks are never cached here.
    """
    token = _READS.set({})
    try:
        yield
    finally:
        _READS.reset(token)


def _once(key, read):
    reads = _READS.get()
    if reads is None:
        return read()
    if key not in reads:
        reads[key] = read()
    return reads[key]


def _manifest(filename):
    return _once(('manifest', filename), lambda: _read(filename))


class PackageResolutionError(ImportError):
    name = 'Error'
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PackageModuleNotFoundError(PackageResolutionError, ModuleNotFoundError):
    pass


def _error(code, message):
    error_type = PackageModuleNotFoundError if code == 'ERR_MODULE_NOT_FOUND' else PackageResolutionError
    raise error_type(code, message)


def package_scope(parent):
    return _once(('scope', parent), lambda: _package_scope(parent))


def _package_scope(parent):
    directory = os.path.dirname(parent)
    while True:
        manifest = os.path.join(directory, 'package.json')
        if os.path.isfile(manifest):
            try:
                value = _manifest(manifest)
                if not isinstance(value, dict):
                    value = {}
            except (ValueError, OSError) as error:
                _error('ERR_INVALID_PACKAGE_CONFIG', 'Invalid package config '+manifest+': '+str(error))
            return directory, value
        if os.path.basename(directory) == 'node_modules':
            return None
        ancestor = os.path.dirname(directory)
        if ancestor == directory:
            return None
        directory = ancestor


def _invalid_segments(value):
    return any(unquote(part).lower() in ('.', '..', 'node_modules') for part in re.split(r'[/\\]', value))


def _target(value, match, captured, internal, directory, conditions):
    if isinstance(value, str):
        if not value.startswith('./'):
            if internal and not value.startswith(('/', '../')) and not urlparse(value).scheme:
                return value.replace('*', captured) if captured is not None else value
            _error('ERR_INVALID_PACKAGE_TARGET', 'Invalid package target '+repr(value)+' for '+match)
        if _invalid_segments(value[2:]):
            _error('ERR_INVALID_PACKAGE_TARGET', 'Invalid package target '+repr(value)+' for '+match)
        if captured is not None and _invalid_segments(captured):
            _error('ERR_INVALID_MODULE_SPECIFIER', 'Invalid module specifier '+match)
        target = value.replace('*', captured) if captured is not None else value
        return urljoin(Path(os.path.join(directory, 'package.json')).as_uri(), target)
    if value is None:
        return None
    if isinstance(value, list):
        last = None
        for candidate in value:
            try:
                result = _target(candidate, match, captured, internal, directory, conditions)
            except PackageResolutionError as error:
                if error.code != 'ERR_INVALID_PACKAGE_TARGET':
                    raise
                last = error
                continue
            if result is _UNDEFINED:
                continue
            if result is None:
                last = None
                continue
            return result
        if last is not None:
            raise last
        return None
    if isinstance(value, dict):
        for key in value:
            if re.fullmatch(r'0|[1-9][0-9]*', key) and int(key) < 4294967295:
                _error('ERR_INVALID_PACKAGE_CONFIG', 'Package exports cannot contain numeric property keys')
        for key, candidate in value.items():
            if key == 'default' or key in conditions:
                result = _target(candidate, match, captured, internal, directory, conditions)
                if result is not _UNDEFINED:
                    return result
        return _UNDEFINED
    _error('ERR_INVALID_PACKAGE_TARGET', 'Invalid package target '+repr(value)+' for '+match)


def _select(mapping, request, internal, directory, conditions):
    if request in mapping and '*' not in request and (internal or not request.endswith('/')):
        return _target(mapping[request], request, None, internal, directory, conditions)
    matches = []
    for key in mapping:
        if key.count('*') != 1:
            continue
        prefix, suffix = key.split('*')
        if request.startswith(prefix) and request.endswith(suffix) and len(request) >= len(key):
            matches.append((len(prefix)+1, len(key), key, request[len(prefix):len(request)-len(suffix) if suffix else None]))
    if matches:
        _, _, key, captured = max(matches, key=lambda item: (item[0], item[1]))
        return _target(mapping[key], key, captured, internal, directory, conditions)
    return _UNDEFINED


def package_export(directory, manifest, request, conditions=CONDITIONS):
    exports = manifest['exports']
    if isinstance(exports, (str, list)):
        exports = {'.': exports}
    elif isinstance(exports, dict):
        kinds = {key.startswith('.') for key in exports}
        if len(kinds) > 1:
            _error('ERR_INVALID_PACKAGE_CONFIG', 'Package exports cannot mix subpaths and conditions')
        if kinds == {False}:
            exports = {'.': exports}
    if not isinstance(exports, dict):
        exports = {}
    result = _select(exports, request, False, directory, conditions)
    if result is None or result is _UNDEFINED:
        _error('ERR_PACKAGE_PATH_NOT_EXPORTED', 'Package subpath '+repr(request)+' is not exported by '+os.path.join(directory, 'package.json'))
    return result


def _finalize(url):
    if re.search(r'%2f|%5c', urlparse(url).path, re.I):
        _error('ERR_INVALID_MODULE_SPECIFIER', 'File URL must not include encoded path separators')
    filename = _parent(url)
    if filename is None:
        _error('ERR_INVALID_URL_SCHEME', 'The URL must be of scheme file')
    if os.path.isdir(filename):
        _error('ERR_UNSUPPORTED_DIR_IMPORT', 'Directory import '+filename+' is not supported')
    if not os.path.isfile(filename):
        _error('ERR_MODULE_NOT_FOUND', 'Cannot find module '+filename)
    return os.path.realpath(filename)


def _legacy(directory, manifest, subpath):
    if subpath != '.':
        return urljoin(Path(os.path.join(directory, 'package.json')).as_uri(), subpath)
    main = manifest.get('main')
    candidates = []
    if isinstance(main, str):
        target = os.path.join(directory, main)
        candidates.extend([target]+[target+extension for extension in ('.js', '.json', '.node')])
        candidates.extend(os.path.join(target, 'index'+extension) for extension in ('.js', '.json', '.node'))
    candidates.extend(os.path.join(directory, 'index'+extension) for extension in ('.js', '.json', '.node'))
    for filename in candidates:
        if os.path.isfile(filename):
            return Path(filename).as_uri()
    _error('ERR_MODULE_NOT_FOUND', 'Cannot find package entry in '+directory)


def resolve_plugin_resource(specifier, parent_url, packages=None, conditions=CONDITIONS, _depth=0):
    if _depth > 64:
        _error('ERR_INVALID_PACKAGE_TARGET', 'Package imports resolution exceeded its limit')
    parent = _parent(parent_url)
    if parent is None:
        _error('ERR_INVALID_URL_SCHEME', 'The URL must be of scheme file')
    if specifier.startswith('#'):
        if specifier == '#' or specifier.startswith('#/') or specifier.endswith('/'):
            _error('ERR_INVALID_MODULE_SPECIFIER', 'Invalid internal imports specifier '+specifier)
        scope = package_scope(parent)
        if scope is None:
            _error('ERR_PACKAGE_IMPORT_NOT_DEFINED', 'Package import '+specifier+' is not defined')
        directory, manifest = scope
        imports = manifest.get('imports')
        target = _select(imports, specifier, True, directory, conditions) if isinstance(imports, dict) else _UNDEFINED
        if target is None or target is _UNDEFINED:
            _error('ERR_PACKAGE_IMPORT_NOT_DEFINED', 'Package import '+specifier+' is not defined')
        return resolve_plugin_resource(target, Path(os.path.join(directory, 'package.json')).as_uri(), packages, conditions, _depth+1)
    if specifier.startswith(('./', '../', '/', '\\', 'file:')) or os.path.isabs(specifier):
        url = specifier if specifier.startswith('file:') else (Path(specifier).as_uri() if os.path.isabs(specifier) else urljoin(parent_url, specifier))
        return _finalize(url)
    if specifier in _BUILTINS or specifier.startswith('node:'):
        _error('ERR_INVALID_URL_SCHEME', 'The URL must be of scheme file')
    name = bare_package_name(specifier)
    if name is None or '%' in name or '\\' in name:
        _error('ERR_INVALID_MODULE_SPECIFIER', 'Invalid package specifier '+specifier)
    request = '.' + specifier[len(name):]
    scope = package_scope(parent)
    if scope is not None and scope[1].get('name') == name and isinstance(scope[1].get('exports'), (str, list, dict)):
        return _finalize(package_export(scope[0], scope[1], request, conditions))
    router = getattr(packages, 'router', None) if packages is not None else None
    if router is not None:
        directory = _once(('directory', id(router), name, parent_url), lambda: router.resource_directory(name, parent_url))
    else:
        directory = _once(('directory', None, name, parent_url), lambda: next((os.path.join(search, name) for search in _search_paths(parent) if os.path.isdir(os.path.join(search, name))), None))
    if directory is None:
        _error('ERR_MODULE_NOT_FOUND', 'Cannot find package '+name)
    try:
        manifest = _manifest(os.path.join(directory, 'package.json'))
    except FileNotFoundError:
        manifest = {}
    except (OSError, ValueError) as error:
        _error('ERR_INVALID_PACKAGE_CONFIG', 'Invalid package config '+os.path.join(directory, 'package.json')+': '+str(error))
    if not isinstance(manifest, dict):
        manifest = {}
    # Node's package reader discards primitive exports values other than strings.
    if isinstance(manifest.get('exports'), (str, list, dict)):
        target = package_export(directory, manifest, request, conditions)
    else:
        target = _legacy(directory, manifest, request)
    return _finalize(target)


resolvePluginResource = resolve_plugin_resource
