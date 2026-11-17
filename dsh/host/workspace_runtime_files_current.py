"""Pinned primary-runtime file operations; work settles independently of awaiters."""
import asyncio
import json
import os
import platform
import shutil
import stat
import sys
import tempfile

from dsh.core.cleanup import CleanupPromise
from dsh.cordis.json_text import stringify_json
from dsh.host.workspace_runtime_manifest_current import parsePrimaryRuntime, workspaceDependencyPaths, _join


def _operation(callback, *args):
    return CleanupPromise(asyncio.get_running_loop().run_in_executor(None, callback, *args))


def _read(root):
    def reject(value):
        raise ValueError('Invalid JSON numeric constant: ' + value)
    with open(_join(root, 'runtime.json'), 'r', encoding='utf-8', errors='replace') as stream:
        return parsePrimaryRuntime(json.loads(stream.read(), parse_constant=reject))


def _link(entry):
    # Python 3.8 exposes Windows junction tags, including on Windows 7.
    return stat.S_ISLNK(entry.st_mode) or getattr(entry, 'st_reparse_tag', 0) in (0xa0000003, 0xa000000c)


def _aliases(root, manifest):
    aliases = {}
    if manifest['platform'] == 'win32':
        return aliases
    interpreter = 'python' + '.'.join(manifest['python'].split('.')[:2])
    for name in ('python', 'python3'):
        relative = 'dependencies/python/bin/' + name
        path = _join(root, relative)
        try:
            entry = os.lstat(path)
        except FileNotFoundError:
            continue
        if not _link(entry):
            continue
        if (os.readlink(path) != interpreter or
                not stat.S_ISREG(os.lstat(_join(root, 'dependencies/python/bin', interpreter)).st_mode)):
            raise ValueError('primary runtime: invalid Python alias ' + relative)
        aliases[relative] = interpreter
    return aliases


def _copy(source, destination, manifest):
    aliases = _aliases(source, manifest)
    excluded = {_join(source, path) for path in aliases}
    def ignore(directory, names):
        return [name for name in names if _join(directory, name) in excluded]
    shutil.copytree(source, destination, symlinks=False, ignore=ignore,
                    copy_function=shutil.copy, dirs_exist_ok=True)
    for path, target in aliases.items():
        os.symlink(target, _join(destination, path))


def _validate(paths):
    for key, kind in (('python', 'file'), ('node', 'file'), ('pnpm', 'file'),
                      ('pythonPackages', 'directory'), ('nodePackages', 'directory')):
        if key not in paths:
            continue
        path = paths[key]
        entry = os.stat(path)
        if not (stat.S_ISREG(entry.st_mode) if kind == 'file' else stat.S_ISDIR(entry.st_mode)):
            raise ValueError('primary runtime: expected ' + kind + ' at ' + path)


def _exists(path):
    try:
        entry = os.lstat(path)
    except FileNotFoundError:
        return False
    if _link(entry):
        raise ValueError('primary runtime: installation path is a filesystem link: ' + path)
    return True


def _platform():
    return 'win32' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'


def _arch():
    if sys.maxsize <= 2 ** 32:
        return 'ia32'
    value = platform.machine().lower()
    return {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64'}.get(value, value)


def _compatible(source):
    manifest = _read(source)
    if manifest['platform'] != _platform() or manifest['arch'] != _arch():
        raise ValueError('primary runtime: incompatible platform or architecture')
    return manifest


def _resolve(source):
    manifest = _compatible(source)
    _aliases(source, manifest)
    paths = workspaceDependencyPaths(source, manifest)
    _validate(paths)
    return paths


def _remove(path, parent):
    # Only this operation's named previous directory or fresh staging is owned.
    absolute, expected = os.path.abspath(path), os.path.abspath(parent)
    if os.path.dirname(absolute) != expected or absolute == expected:
        raise ValueError('primary runtime: cleanup path escapes installation parent')
    try:
        entry = os.lstat(absolute)
    except FileNotFoundError:
        return
    if _link(entry):
        if os.name == 'nt' and stat.S_ISDIR(entry.st_mode):
            os.rmdir(absolute)
        else:
            os.unlink(absolute)
    elif stat.S_ISDIR(entry.st_mode):
        def readonly_retry(callback, failed, info):
            owned = os.lstat(failed)
            if _link(owned) or not stat.S_ISREG(owned.st_mode) or owned.st_nlink != 1 or owned.st_mode & stat.S_IWRITE:
                raise info[1]
            os.chmod(failed, owned.st_mode | stat.S_IWRITE)
            callback(failed)
        shutil.rmtree(absolute, onerror=readonly_retry)
    else:
        os.unlink(absolute)


def _install(source, root):
    manifest = _compatible(source)
    parent = os.path.dirname(root) or '.'
    os.makedirs(parent, exist_ok=True)
    previous = root + '.previous'
    previous_exists, root_exists = _exists(previous), _exists(root)
    if not root_exists and previous_exists:
        os.rename(previous, root)
    if _exists(_join(root, 'runtime.json')) and stringify_json(_read(root)) == stringify_json(manifest):
        _aliases(root, manifest)
        paths = workspaceDependencyPaths(root, manifest)
        _validate(paths)
        return paths
    staging = tempfile.mkdtemp(prefix='.primary-runtime-', dir=parent)
    try:
        _copy(source, staging, manifest)
        _validate(workspaceDependencyPaths(staging, manifest))
        _remove(previous, parent)
        replacing = _exists(root)
        if replacing:
            os.rename(root, previous)
        try:
            os.rename(staging, root)
        except BaseException:
            if replacing:
                os.rename(previous, root)
            raise
        _remove(previous, parent)
    finally:
        _remove(staging, parent)
    return workspaceDependencyPaths(root, manifest)


def readPrimaryRuntime(root): return _operation(_read, root)
def primaryRuntimePythonAliases(root, manifest): return _operation(_aliases, root, manifest)
def copyPrimaryRuntime(source, destination, manifest): return _operation(_copy, source, destination, manifest)
def resolvePrimaryRuntime(source): return _operation(_resolve, source)
def installPrimaryRuntime(source, root): return _operation(_install, source, root)
