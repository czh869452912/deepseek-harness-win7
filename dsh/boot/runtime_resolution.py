"""Read-only package-generation construction from installation/profile inputs."""
import json
import os
from collections import deque
from pathlib import Path
from dsh.cordis.environment import resolve_dsh_home


class _Record(dict):
    def _readonly(self, *args, **kwargs):
        raise TypeError('Runtime resolution records are immutable')
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _readonly
    __ior__ = _readonly


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _read(anchor):
    with open(anchor, 'r', encoding='utf-8') as stream:
        return json.load(stream)


def _canonical(anchor):
    return os.path.join(str(Path(os.path.dirname(anchor)).resolve(strict=True)), os.path.basename(anchor))


def _dependencies(manifest):
    return [name for field in ('dependencies', 'peerDependencies', 'optionalDependencies') for name in (manifest.get(field) or {})]


def native_package_dir(anchor, name):
    """Probe Node's actual ancestor chain; do not synthesize workspace packages."""
    directory = os.path.dirname(os.path.abspath(anchor))
    while True:
        if os.path.basename(directory) != 'node_modules':
            candidate = os.path.join(directory, 'node_modules', name)
            if os.path.exists(os.path.join(candidate, 'package.json')):
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def _installation(anchor, skipped):
    from dsh.boot.profile import read_profile_manifest
    canonical = _canonical(anchor)
    manifest = _read(canonical)
    entries = {}
    if 'name' in manifest:
        entries[manifest['name']] = dict(name=manifest['name'], packageDir=os.path.dirname(anchor),
            version=manifest.get('version'), declarer=canonical, scope='installation')
    queue = deque([(canonical, manifest)])
    while queue:
        parent, current = queue.popleft()
        for name in _dependencies(current):
            if name in entries:
                continue
            directory = native_package_dir(parent, name)
            if directory is None:
                continue
            manifest_path = _canonical(os.path.join(directory, 'package.json'))
            try:
                child = read_profile_manifest('dsh', directory) if name in skipped else _read(manifest_path)
            except Exception:
                if name not in skipped:
                    raise
                continue
            entries[name] = dict(name=name, packageDir=directory, version=child.get('version'),
                declarer=parent, scope='installation')
            queue.append((manifest_path, child))
    return entries


def _profile_packages(profile, reserved):
    entries, visited = {}, set(reserved)
    layers = _field(profile, 'layers', [])
    for layer in layers:
        if _field(layer, 'packageName') in reserved:
            continue
        anchor = _canonical(os.path.join(_field(layer, 'packageDir'), 'package.json'))
        manifest = _read(anchor)
        if 'name' not in manifest:
            continue
        name = manifest['name']
        if name not in visited:
            visited.add(name)
            entries[name] = dict(name=name, packageDir=os.path.dirname(anchor), version=manifest.get('version'), declarer=anchor, scope='profile')
        queue = deque([(anchor, manifest)])
        while queue:
            parent, current = queue.popleft()
            for name in _dependencies(current):
                if name in visited:
                    continue
                directory = native_package_dir(parent, name)
                if directory is None:
                    continue
                visited.add(name)
                manifest_path = _canonical(os.path.join(directory, 'package.json'))
                child = _read(manifest_path)
                entries[name] = dict(name=name, packageDir=directory, version=child.get('version'), declarer=parent, scope='profile')
                queue.append((manifest_path, child))
    for layer in layers:
        entries.pop(_field(layer, 'packageName'), None)
    return entries


def _links(modules):
    if not os.path.isdir(modules):
        return []
    from dsh.boot.profile import is_symlink_or_junction
    result = []
    for name in os.listdir(modules):
        path = os.path.join(modules, name)
        if is_symlink_or_junction(path):
            result.append(path)
        elif name.startswith('@') and os.path.isdir(path):
            for child in os.listdir(path):
                candidate = os.path.join(path, child)
                if is_symlink_or_junction(candidate):
                    result.append(candidate)
    return result


def _linked_roots(profile_dir, profiles_dir):
    modules = os.path.join(profile_dir, 'node_modules')
    links = _links(modules)
    if not links:
        return []
    tree = os.path.realpath(profiles_dir)+os.sep
    excluded = [tree, str(Path(profile_dir).resolve(strict=True))+os.sep]
    roots = []
    for link in links:
        try:
            real_path = str(Path(link).resolve(strict=True))
        except FileNotFoundError:
            continue
        if any(real_path+os.sep == prefix or real_path.startswith(prefix) for prefix in excluded) or not os.path.isdir(real_path):
            continue
        roots.append(dict(name=os.path.relpath(link, modules).replace(os.sep, '/'), realPath=real_path))
    return sorted(roots, key=lambda row: row['name'])


class ProfileRuntimeResolution:
    """Immutable table retaining only the locations needed for a successor."""
    def __init__(self, source, table):
        object.__setattr__(self, '_source', _Record(source))
        object.__setattr__(self, 'profilesDir', table['profilesDir'])
        object.__setattr__(self, 'profileDir', table.get('profileDir'))
        object.__setattr__(self, 'localPackageNames', tuple(table['localPackageNames']))
        object.__setattr__(self, 'entries', tuple(_Record(row) for row in table['entries']))
        object.__setattr__(self, 'linkedRoots', tuple(_Record(row) for row in table['linkedRoots']))

    def __setattr__(self, name, value):
        raise TypeError('Runtime resolution is immutable')

    def __delattr__(self, name):
        raise TypeError('Runtime resolution is immutable')

    def to_dict(self):
        return dict(profilesDir=self.profilesDir, profileDir=self.profileDir, localPackageNames=list(self.localPackageNames),
            entries=[dict(row) for row in self.entries], linkedRoots=[dict(row) for row in self.linkedRoots])

    async def compute_latest_resolution(self):
        from dsh.boot.profile import load_profile_directory
        source = self._source
        profile = None if source.get('profileDir') is None else load_profile_directory('dsh', source['profileDir'], source['installAnchor'])
        return await create_runtime_resolution(dict(installAnchor=source['installAnchor'], home=source['home'], profile=profile))

    computeLatestResolution = compute_latest_resolution


async def create_runtime_resolution(options):
    anchor = options['installAnchor']
    profile = options.get('profile')
    home = options.get('home') or resolve_dsh_home()
    profiles_dir = os.path.join(home, 'profiles')
    profile_dir = _field(profile, 'dir')
    manifest = None
    if profile is not None:
        try:
            manifest = _read(os.path.join(profile_dir, 'package.json'))
        except FileNotFoundError:
            pass
    skipped = {_field(row, 'packageName') for row in _field(profile, 'skippedBundles', [])}
    installation = _installation(anchor, skipped)
    local_names = [] if manifest is None else [name for name in _dependencies(manifest)
        if os.path.exists(os.path.join(profile_dir, 'node_modules', name, 'package.json'))]
    selected = {} if profile is None else _profile_packages(profile, installation)
    table = dict(profilesDir=profiles_dir, profileDir=profile_dir, localPackageNames=local_names,
        entries=list(installation.values())+list(selected.values()), linkedRoots=[] if profile is None else _linked_roots(profile_dir, profiles_dir))
    return ProfileRuntimeResolution(dict(installAnchor=anchor, profileDir=profile_dir, home=home), table)


createRuntimeResolution = create_runtime_resolution
