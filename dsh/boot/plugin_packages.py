"""Profile-scoped package metadata routing and atomic generation publication.

This service does not install JavaScript ESM/CommonJS hooks. Python module
loading consumes the published router explicitly at its own boundary.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from dsh.cordis.service import Service
from dsh.boot.runtime_resolution import ProfileRuntimeResolution, _field, _read, native_package_dir

# Node 24.9.0's unprefixed builtins, frozen with the candidate toolchain.
_BUILTINS = set(('''_http_agent _http_client _http_common _http_incoming _http_outgoing _http_server
_stream_duplex _stream_passthrough _stream_readable _stream_transform _stream_wrap _stream_writable
_tls_common _tls_wrap assert assert/strict async_hooks buffer child_process cluster console constants
crypto dgram diagnostics_channel dns dns/promises domain events fs fs/promises http http2 https
inspector inspector/promises module net os path path/posix path/win32 perf_hooks process punycode
querystring readline readline/promises repl stream stream/consumers stream/promises stream/web
string_decoder sys timers timers/promises tls trace_events tty url util util/types v8 vm wasi
worker_threads zlib''').split())


def bare_package_name(request):
    if not request or request[0] in './\\#' or ':' in request or request in _BUILTINS:
        return None
    first = request.find('/')
    if request[0] != '@':
        return request if first < 0 else request[:first]
    if first < 0:
        return None
    second = request.find('/', first + 1)
    return request if second < 0 else request[:second]


def _parent(url):
    parsed = urlparse(url)
    if parsed.scheme != 'file' or parsed.query or parsed.fragment:
        # URL search/hash do not affect Node's fileURLToPath.
        if parsed.scheme != 'file':
            return None
    path = url2pathname(parsed.path)
    return ('//' + parsed.netloc + path) if parsed.netloc else path


def _canonical(path):
    try:
        return str(Path(path).resolve(strict=True))
    except OSError:
        return os.path.abspath(path)


def _same(left, right):
    return left == right or _canonical(left) == _canonical(right)


def _prefixes(path):
    return list(dict.fromkeys([os.path.abspath(path) + os.sep, _canonical(path) + os.sep]))


def _search_paths(parent):
    directory = os.path.dirname(parent)
    while True:
        if os.path.basename(directory) != 'node_modules':
            yield os.path.join(directory, 'node_modules')
        ancestor = os.path.dirname(directory)
        if ancestor == directory:
            return
        directory = ancestor


def _self_reference(parent):
    current = os.path.dirname(parent)
    while True:
        manifest = os.path.join(current, 'package.json')
        if os.path.exists(manifest):
            try:
                value = _read(manifest)
                return value['name'] if isinstance(value.get('name'), str) and value.get('exports') is not None else False
            except (OSError, ValueError, AttributeError, TypeError):
                return None
        if os.path.basename(current) == 'node_modules':
            return False
        ancestor = os.path.dirname(current)
        if ancestor == current:
            return False
        current = ancestor


class ResolutionRestartRequired(RuntimeError):
    name = 'ResolutionRestartRequired'


class ResolutionRouter:
    """Metadata branch of the Source router, with one published generation."""
    def __init__(self, resolution):
        self._moves = {}
        self._linked_targets = {row['name']: row['realPath'] for row in _field(resolution, 'linkedRoots', [])}
        self._publish(resolution)

    def _publish(self, resolution):
        self.resolution = resolution
        self.entries = {row['name']: dict(row, realDir=_canonical(row['packageDir'])) for row in _field(resolution, 'entries', [])}
        self._trees = _prefixes(_field(resolution, 'profilesDir'))
        active = _field(resolution, 'profileDir')
        self._active = [] if active is None else _prefixes(active)
        self._installation = [prefix for row in self.entries.values() if row['scope'] == 'installation' for prefix in _prefixes(row['packageDir'])]
        self._linked = [prefix for row in _field(resolution, 'linkedRoots', []) for prefix in _prefixes(row['realPath'])]
        self._locals = set(_field(resolution, 'localPackageNames', []))
        self._routes = {}
        self._owners = {}

    def _layer(self, parent):
        tree = next((prefix for prefix in self._trees if parent.startswith(prefix)), None)
        active = next((prefix for prefix in self._active if parent.startswith(prefix)), None)
        directory = tree + parent[len(tree):].split(os.sep)[0] if tree else (active[:-1] if active else None)
        if directory is not None:
            return dict(kind='profile', active=active is not None, prefix=directory + os.sep,
                nativeAfter=os.path.join(os.path.dirname(directory), 'package.json'))
        if any(parent.startswith(prefix) for prefix in self._linked) and not any(parent.startswith(prefix) for prefix in self._installation):
            return dict(kind='linked')
        return None

    def package_dir(self, specifier, parent_url):
        name = bare_package_name(specifier)
        parent = _parent(parent_url)
        if name is None or parent is None:
            return None
        layer = self._layer(parent)
        if layer is None:
            return native_package_dir(parent, name)
        key = (parent_url, name)
        state = self._routes.get(key)
        if state is None:
            state = self._route(name, parent, layer)
            if layer['kind'] == 'profile' and state['kind'] != 'after':
                self._routes[key] = state
        if state.get('directory') is not None:
            return state['directory']
        found = native_package_dir(state.get('parent', parent), name)
        if found is not None:
            state['directory'] = found
        return found

    packageDir = package_dir

    def resource_directory(self, name, parent_url):
        """Module lookup also admits legacy directories without package.json."""
        parent = _parent(parent_url)
        if parent is None:
            return None
        layer = self._layer(parent)
        state = dict(kind='native') if layer is None else self._routes.get((parent_url, name))
        if state is None:
            state = self._route(name, parent, layer)
            if layer['kind'] == 'profile' and state['kind'] != 'after':
                self._routes[(parent_url, name)] = state
        if state.get('directory') is not None:
            return state['directory']
        for search in _search_paths(state.get('parent', parent)):
            candidate = os.path.join(search, name)
            if os.path.isdir(candidate):
                return candidate
        return None

    def _route(self, name, parent, layer):
        if layer['kind'] == 'profile' and layer['active'] and name in self._locals:
            return dict(kind='native')
        if layer['kind'] == 'linked':
            own = _self_reference(parent)
        else:
            if parent not in self._owners:
                self._owners[parent] = _self_reference(parent)
            own = self._owners[parent]
        if own == name or own is None:
            return dict(kind='native')
        target = self.entries.get(name)
        for search in _search_paths(parent):
            if layer['kind'] == 'profile':
                if not search.startswith(layer['prefix']):
                    break
            elif target is not None:
                try:
                    peers = _read(os.path.join(os.path.dirname(search), 'package.json')).get('peerDependencies')
                except (OSError, ValueError, AttributeError):
                    peers = None
                if isinstance(peers, dict) and name in peers:
                    return dict(kind='interception', directory=target['packageDir'])
            if layer['kind'] == 'linked' and target is None:
                return dict(kind='native')
            candidate = os.path.join(search, name)
            if os.path.isdir(candidate):
                return dict(kind='native', directory=candidate)
        if layer['kind'] == 'linked':
            return dict(kind='native')
        if target is not None and (target['scope'] == 'installation' or layer['active']):
            return dict(kind='interception', directory=target['packageDir'])
        return dict(kind='after', parent=layer['nativeAfter'])

    def replace(self, successor):
        if any(_field(successor, name) != _field(self.resolution, name) for name in ('profilesDir', 'profileDir')):
            raise RuntimeError('profile resolution: a successor cannot change its profile scope')
        entries = {row['name']: row for row in _field(successor, 'entries', [])}
        rejected = []
        for name, current in self.entries.items():
            next_row = entries.get(name)
            if next_row is None and current['scope'] == 'profile':
                continue
            if next_row is not None and current['scope'] == next_row['scope'] == 'profile':
                different = current['realDir'] != _canonical(next_row['packageDir'])
            else:
                different = next_row is None or current['scope'] != next_row['scope'] or not _same(current['packageDir'], next_row['packageDir'])
                if not different and current['scope'] == 'installation':
                    different = not _same(current['declarer'], next_row['declarer']) or current.get('version') != next_row.get('version')
            if different:
                rejected.append('profile resolution: replacing ' + json.dumps(name, ensure_ascii=False) + ' requires a process restart')
        for name in dict.fromkeys(_field(successor, 'localPackageNames', [])):
            if name not in self._locals and name in self.entries:
                rejected.append('profile resolution: overriding ' + json.dumps(name, ensure_ascii=False) + ' locally requires a process restart')
        if rejected:
            raise ResolutionRestartRequired('; '.join(rejected))
        roots = {row['name']: row['realPath'] for row in _field(successor, 'linkedRoots', [])}
        targets = dict(self._linked_targets)
        for name, previous in self._linked_targets.items():
            entry = entries.get(name)
            target = roots.get(name) or (_canonical(entry['packageDir']) if entry and entry['scope'] == 'profile' else None)
            if target is None or _same(previous, target):
                continue
            old = _prefixes(previous)
            new = target + os.sep
            self._moves = {key: new if value in old else value for key, value in self._moves.items()}
            self._moves.update({key: new for key in old})
            targets[name] = target
        targets.update(roots)
        self._linked_targets = targets
        active = {prefix for path in list(roots.values()) + [_canonical(row['packageDir']) for row in entries.values()] for prefix in _prefixes(path)}
        self._moves = {key: value for key, value in self._moves.items() if key not in active and key != value}
        self._publish(successor)

    def relocate(self, filename, parent=None):
        prefix = max((key for key in self._moves if filename.startswith(key)), key=len, default='')
        if not prefix or (parent is not None and parent.startswith(prefix)):
            return filename
        target = self._moves[prefix] + filename[len(prefix):]
        return target if os.path.exists(target) else filename


class PluginPackages(Service):
    def __init__(self, ctx, config=None):
        self._current = (config or {}).get('resolution')
        self.router = None if self._current is None else ResolutionRouter(self._current)
        self._packages = {}
        super().__init__(ctx, 'pluginPackages')

    @property
    def resolution(self):
        return self._current

    def replace(self, successor):
        if self.router is None:
            raise RuntimeError('plugin-packages: runtime resolution is not installed')
        self.router.replace(successor)
        self._current = successor
        self._packages = {}

    async def refresh(self):
        if not isinstance(self._current, ProfileRuntimeResolution):
            raise RuntimeError('plugin-packages: the installed runtime resolution cannot be recomputed')
        self.replace(await self._current.compute_latest_resolution())

    def package_of(self, specifier, parent_url):
        name = bare_package_name(specifier)
        if name is None:
            return None
        if self.router is None:
            parent = _parent(parent_url)
            directory = None if parent is None else native_package_dir(parent, name)
        else:
            directory = self.router.package_dir(name, parent_url)
        if directory is None:
            return None
        key = (directory, name)
        if key not in self._packages:
            manifest_path = os.path.join(directory, 'package.json')
            package = None
            if os.path.exists(manifest_path):
                manifest = _read(manifest_path)
                package = dict(name=manifest.get('name') if isinstance(manifest.get('name'), str) else name,
                    version=manifest.get('version') if isinstance(manifest.get('version'), str) else None,
                    dir=directory, manifestPath=manifest_path, manifest=manifest)
            self._packages[key] = package
        return self._packages[key]

    packageOf = package_of

    def resolve_resource(self, specifier, parent_url):
        from dsh.boot.package_resolution import resolve_plugin_resource
        return resolve_plugin_resource(specifier, parent_url, self)

    resolveResource = resolve_resource


barePackageName = bare_package_name
