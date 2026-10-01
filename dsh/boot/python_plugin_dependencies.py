"""Locked expanded Python libraries with process-wide compatible ownership."""
import ast
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import uuid

_POOL = {}
_PACKAGES = {}
_LOCK = threading.RLock()
_PIN = re.compile(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)\Z')


def pin(value):
    match = _PIN.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError('Python dependencies require exact name==version pins')
    return re.sub(r'[-_.]+', '-', match.group(1)).lower(), match.group(2)


def identity(row):
    value = {key: row[key] for key in ('name', 'version', 'imports', 'requires', 'files')}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def forget_importers(root):
    prefix = os.path.normcase(os.path.abspath(root))
    for key in list(sys.path_importer_cache):
        if not isinstance(key, str):
            continue
        path = os.path.normcase(os.path.abspath(key))
        if path == prefix or path.startswith(prefix + os.sep):
            sys.path_importer_cache.pop(key, None)


def host_collision(root):
    if any(root.casefold() in [item.casefold() for item in row['imports']] for row in _POOL.values()):
        return False
    if root.casefold().startswith('_dsh_python_') or root.casefold() in {'dsh', 'apps', 'reference', 'scripts', 'packages', 'tests', '__main__'}:
        return True
    # Windows filenames alias case, while sys.modules keys do not.
    if root.casefold() in {name.split('.')[0].casefold() for name in sys.modules}:
        return True
    for name in (root, root.lower()):
        if importlib.util.find_spec(name) is not None:
            return True
    return False


def libraries(directory, manifest):
    """Validate a full authored file closure without importing its Python code."""
    from dsh.boot.python_package import inside
    from dsh.boot.python_plugins import regular_tree
    dependencies = manifest['dsh']['python']['dependencies']
    if not isinstance(dependencies, list):
        raise ValueError('Python dependencies must be an array')
    roots = [pin(value) for value in dependencies]
    if len({name for name, _ in roots}) != len(roots):
        raise ValueError('duplicate Python dependencies')
    lock = manifest['dsh'].get('pythonDependencies')
    if not roots and lock is None:
        return []
    if (not isinstance(lock, dict) or set(lock) != {'formatVersion', 'python', 'abi', 'platform', 'packages'}
            or type(lock['formatVersion']) is not int or lock['formatVersion'] != 1
            or lock['python'] != [3, 8, 10] or any(type(part) is not int for part in lock['python'])
            or lock['abi'] != 'none' or lock['platform'] != 'any'
            or not isinstance(lock['packages'], list) or not lock['packages']):
        raise ValueError('Python dependencies require a Python 3.8.10 expanded-file closure lock')
    rows, imports, sources = {}, {}, set()
    for original in lock['packages']:
        if not isinstance(original, dict) or set(original) != {'name', 'version', 'sourceRoot', 'imports', 'requires', 'files', 'origin'}:
            raise ValueError('invalid locked Python dependency')
        row = dict(original)
        if not isinstance(row['name'], str) or not isinstance(row['version'], str):
            raise ValueError('invalid Python dependency name or version')
        name, version = pin(row['name'] + '==' + row['version'])
        if name != row['name'] or name in rows:
            raise ValueError('locked Python dependency names must be unique and normalized')
        if not isinstance(row['origin'], str) or not row['origin'].strip():
            raise ValueError('Python dependency build origin is required')
        if (not isinstance(row['requires'], list) or not isinstance(row['imports'], list)
                or not row['imports'] or any(not isinstance(item, str) or not item.isidentifier() for item in row['imports'])
                or not isinstance(row['files'], dict) or not row['files']):
            raise ValueError('invalid Python dependency imports, requirements or file hashes')
        path = inside(directory, row['sourceRoot'])
        if not os.path.isdir(path):
            raise ValueError('Python dependency source is missing: ' + name)
        normalized = os.path.normcase(os.path.realpath(path))
        if normalized in sources or any(os.path.commonpath([normalized, source]) in (normalized, source) for source in sources):
            raise ValueError('Python dependency source roots must not overlap')
        plugin_source = os.path.normcase(os.path.realpath(inside(directory, manifest['dsh']['python']['sourceRoot'])))
        if os.path.commonpath([normalized, plugin_source]) in (normalized, plugin_source):
            raise ValueError('Python dependency source must be separate from plugin source')
        sources.add(normalized)
        actual, code_roots = {}, set()
        for relative, filename in regular_tree(path):
            if relative.lower().endswith(('.pyc', '.pyo', '.pth', '.dylib')):
                raise ValueError('Python dependencies require source files, not bytecode or path hooks')
            with open(filename, 'rb') as stream:
                body = stream.read()
            actual[relative] = hashlib.sha256(body).hexdigest()
            if relative.lower().endswith('.py'):
                top = relative.split('/')[0]
                code_roots.add(top[:-3] if top.lower().endswith('.py') else top)
                try:
                    compile(body, filename, 'exec', ast.PyCF_ONLY_AST, dont_inherit=True)
                except SyntaxError as error:
                    raise ValueError('invalid Python dependency syntax: ' + relative) from error
        if actual != row['files']:
            raise ValueError('Python dependency file hashes differ: ' + name)
        row['imports'] = sorted(row['imports'])
        row['requires'] = sorted(target + '==' + version for target, version in (pin(value) for value in row['requires']))
        if code_roots != set(row['imports']):
            raise ValueError('Python dependency import roots differ from the locked code: ' + name)
        for root in row['imports']:
            if root.casefold() in imports or host_collision(root):
                raise ValueError('Python dependency import conflicts with host or another library: ' + root)
            imports[root.casefold()] = name
            if not (os.path.isfile(os.path.join(path, root + '.py')) or os.path.isfile(os.path.join(path, root, '__init__.py'))):
                raise ValueError('Python dependency import requires a module or regular package: ' + root)
        row['path'], row['fingerprint'] = path, identity(row)
        rows[name] = row
    visited = set()
    def visit(name, version):
        if name not in rows or rows[name]['version'] != version:
            raise ValueError('Python dependency closure is missing or mismatched: ' + name + '==' + version)
        if name in visited:
            return
        visited.add(name)
        required = [pin(value) for value in rows[name]['requires']]
        if len({item[0] for item in required}) != len(required):
            raise ValueError('duplicate transitive Python dependencies: ' + name)
        for target in required:
            visit(*target)
    for target in roots:
        visit(*target)
    if visited != set(rows):
        raise ValueError('Python dependency lock includes unreachable libraries')
    return list(rows.values())


def profile_libraries(directory, candidate=None, replacing=None):
    from dsh.boot.profile import read_profile_manifest
    from dsh.boot.python_package import read_descriptor, inside
    manifest = read_profile_manifest('dsh', directory) if os.path.isfile(os.path.join(directory, 'package.json')) else {}
    paths = [inside(directory, 'node_modules/' + name) for name in manifest.get('dsh', {}).get('pythonPlugins', {}) if name != replacing]
    if candidate is not None:
        paths.append(candidate)
    graph, roots, packages = {}, {}, {}
    for path in paths:
        rows = libraries(path, read_descriptor(path)[0])
        if not rows:
            continue
        packages[os.path.normcase(os.path.realpath(path))] = rows
        for row in rows:
            previous = graph.get(row['name'])
            if previous is not None and previous['fingerprint'] != row['fingerprint']:
                raise ValueError('incompatible Python dependency in profile: {}=={} versus {}=={} (lock differs)'.format(
                    previous['name'], previous['version'], row['name'], row['version']))
            for root in row['imports']:
                if root.casefold() in roots and roots[root.casefold()] != row['name']:
                    raise ValueError('Python dependency import name conflicts in profile: ' + root)
                roots[root.casefold()] = row['name']
            graph[row['name']] = row
    return graph, packages


def import_identity(directory, rows, namespace=None):
    if not rows:
        return ''
    key = os.path.normcase(os.path.realpath(directory))
    owner = _PACKAGES.get(key)
    if owner is None or owner['fingerprints'] != {row['name']: row['fingerprint'] for row in rows}:
        raise RuntimeError('Python dependencies require a canonical profile runtime lease')
    if namespace is not None:
        owner['namespaces'].add(namespace)
    return ':'.join(_POOL[row['name']]['epoch'] for row in sorted(rows, key=lambda row: row['name']))


class PythonDependencyLease:
    """Compatible profiles share immutable temporary code, never mutable installs."""
    def __init__(self, directory):
        self.names, self.packages, self.closed = [], [], False
        with _LOCK:
            graph, packages = profile_libraries(directory)
            for row in graph.values():
                previous = _POOL.get(row['name'])
                if previous is not None and previous['fingerprint'] != row['fingerprint']:
                    raise RuntimeError('Python dependency conflicts with an active profile: ' + row['name'])
                for other in _POOL.values():
                    if other['name'] != row['name'] and set(root.casefold() for root in other['imports']) & set(root.casefold() for root in row['imports']):
                        raise RuntimeError('Python dependency import conflicts with an active profile: ' + row['name'])
            for key, rows in packages.items():
                if key in _PACKAGES and _PACKAGES[key]['fingerprints'] != {row['name']: row['fingerprint'] for row in rows}:
                    raise RuntimeError('Python dependency configuration changed for an active package')
            try:
                for name, row in graph.items():
                    if name not in _POOL:
                        temporary = tempfile.TemporaryDirectory(prefix='dsh-python-dependencies-')
                        try:
                            for relative, expected in row['files'].items():
                                from dsh.boot.python_package import inside
                                source = inside(row['path'], relative)
                                with open(source, 'rb') as stream:
                                    body = stream.read()
                                if hashlib.sha256(body).hexdigest() != expected:
                                    raise ValueError('Python dependency changed during runtime preparation: ' + name)
                                target = inside(temporary.name, relative)
                                os.makedirs(os.path.dirname(target), exist_ok=True)
                                with open(target, 'xb') as stream:
                                    stream.write(body)
                            _POOL[name] = dict(row, temporary=temporary, epoch=uuid.uuid4().hex, references=0)
                            sys.path.insert(0, temporary.name)
                        except BaseException:
                            temporary.cleanup()
                            raise
                    _POOL[name]['references'] += 1
                    self.names.append(name)
                for key, rows in packages.items():
                    owner = _PACKAGES.setdefault(key, dict(references=0, fingerprints={row['name']: row['fingerprint'] for row in rows}, namespaces=set()))
                    owner['references'] += 1
                    self.packages.append(key)
                importlib.invalidate_caches()
            except BaseException:
                self.close()
                raise

    def close(self):
        with _LOCK:
            if self.closed:
                return
            self.closed = True
            for key in self.packages:
                owner = _PACKAGES[key]
                owner['references'] -= 1
                if owner['references']:
                    continue
                for namespace in owner['namespaces']:
                    for name in list(sys.modules):
                        if name == namespace or name.startswith(namespace + '.'):
                            sys.modules.pop(name, None)
                del _PACKAGES[key]
                forget_importers(key)
            for name in self.names:
                row = _POOL[name]
                row['references'] -= 1
                if row['references']:
                    continue
                for root in row['imports']:
                    for module in list(sys.modules):
                        if module.casefold() == root.casefold() or module.casefold().startswith(root.casefold() + '.'):
                            sys.modules.pop(module, None)
                path = row['temporary'].name
                while path in sys.path:
                    sys.path.remove(path)
                forget_importers(path)
                row['temporary'].cleanup()
                del _POOL[name]
            importlib.invalidate_caches()
