"""Private Git source preparation; run inside an owned captured Python child."""
import json
import gzip
import ctypes
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit, unquote

from dsh.boot import python_plugins as store
from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.python_package import relative_parts
from dsh.boot.python_package_local import publish_local
from dsh.boot.python_package_query import PackageQueryError
from dsh.boot.python_package_tarball import unpack_tarball

MAX_REPOSITORY_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = store.MAX_BYTES
GIT_TIMEOUT = 90
_MARKER = '.native-git-owner.json'
_HOSTS = dict(github='github.com', gitlab='gitlab.com', bitbucket='bitbucket.org', gist='gist.github.com')


def public_repository(repository):
    scp = re.fullmatch(r'[^@/]+@([^:]+):(.+)', repository)
    if scp:
        return 'ssh://' + scp[1] + '/' + scp[2]
    parsed = urlsplit(repository)
    hostname = parsed.hostname or ''
    host = '[' + hostname + ']' if ':' in hostname else hostname
    if parsed.port is not None:
        host += ':' + str(parsed.port)
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, '', ''))


def git_source(spec):
    parsed = parse_install_spec(spec)
    if parsed['kind'] != 'git':
        raise PackageQueryError('ERR_DSH_GIT_SPEC', 'a Git package source is required')
    repository, _, fragment = parsed['spec'].partition('#')
    shorthand = re.match(r'^(github|gitlab|bitbucket|gist):', repository, re.I)
    if shorthand:
        repository = 'https://' + _HOSTS[shorthand[1].lower()] + '/' + repository[shorthand.end():]
        if not repository.lower().endswith('.git'):
            repository += '.git'
    repository = re.sub(r'^git\+', '', repository, flags=re.I)
    if any(ord(char) < 32 for char in repository):
        raise PackageQueryError('ERR_DSH_GIT_SPEC', 'Git source contains control characters')
    if not repository.startswith('git@'):
        url = urlsplit(repository)
        if url.scheme not in ('http', 'https', 'ssh', 'git', 'file') or url.query:
            raise PackageQueryError('ERR_DSH_GIT_SPEC', 'unsupported Git repository URL')
    parts = fragment.split('&') if fragment else []
    paths = [part[5:] for part in parts if part.startswith('path:')]
    refs = [part for part in parts if part and not part.startswith('path:')]
    if len(paths) > 1 or len(refs) > 1:
        raise PackageQueryError('ERR_DSH_GIT_SPEC', 'Git source requires one ref and at most one package directory')
    directory = unquote(paths[0], encoding='utf-8', errors='strict').strip('/') if paths else ''
    if directory:
        relative_parts(directory)
    ref = refs[0] if refs else 'HEAD'
    if ref.startswith('-') or ':' in ref or any(ord(char) < 32 for char in ref):
        raise PackageQueryError('ERR_DSH_GIT_SPEC', 'unsupported Git revision selector')
    if re.fullmatch(r'[0-9a-fA-F]{40}', ref):
        ref = ref.lower()
    return dict(repository=repository, publicRepository=public_repository(repository), ref=ref, directory=directory)


def create_git_workspace(parent):
    external = None
    if os.name == 'nt' and len(os.path.abspath(os.path.join(parent, 'git-workspace'))) > 160:
        # Keep Git's own discovery/pack paths below its remaining MAX_PATH
        # boundaries. This separate owned payload is still joined/cleaned by
        # the parent after the captured process tree has fully drained.
        base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp')
        if not os.path.isabs(base) or not os.path.isdir(base) or store.reparse(base):
            raise ValueError('a real local temporary directory is required for Git preparation')
        external = tempfile.mkdtemp(prefix='dsh-native-git-', dir=base)
        parent = external
    workspace = os.path.join(parent, 'git-workspace')
    try:
        os.mkdir(workspace)
        value = dict(formatVersion=1, owner='native-git-preparation', directory=os.path.normcase(os.path.realpath(workspace)))
        if external is not None:
            value['externalParent'] = os.path.normcase(os.path.realpath(external))
        store.atomic_bytes(os.path.join(workspace, _MARKER), store.json_bytes(value))
    except BaseException:
        if os.path.isdir(workspace) and not os.listdir(workspace):os.rmdir(workspace)
        if external is not None and not os.listdir(external):os.rmdir(external)
        raise
    return workspace


def _owned_workspace(workspace):
    if os.path.basename(workspace) != 'git-workspace' or store.reparse(workspace):
        raise ValueError('Git preparation requires its owned workspace')
    marker = os.path.join(workspace, _MARKER)
    if store.reparse(marker):
        raise ValueError('Git workspace marker must not be a link')
    with open(marker, encoding='utf-8') as stream:
        value = json.load(stream)
    expected = dict(formatVersion=1, owner='native-git-preparation', directory=os.path.normcase(os.path.realpath(workspace)))
    if isinstance(value, dict) and 'externalParent' in value:
        parent = os.path.dirname(os.path.abspath(workspace))
        if not os.path.basename(parent).startswith('dsh-native-git-') or store.reparse(parent):
            raise ValueError('Git external workspace owner differs')
        expected['externalParent'] = os.path.normcase(os.path.realpath(parent))
    if value != expected:
        raise ValueError('Git workspace owner differs')
    return value


def cleanup_git_workspace(workspace):
    if not os.path.lexists(workspace):
        return
    owner = _owned_workspace(workspace)
    if 'externalParent' in owner and os.listdir(owner['externalParent']) != ['git-workspace']:
        raise ValueError('Git external workspace contains unknown sibling assets')
    repository = os.path.join(workspace, 'repository')
    objects = os.path.join(workspace, 'repository', 'objects')
    for path in (repository, objects):
        if os.path.lexists(path) and store.reparse(path):
            raise ValueError('Git preparation object path must not be a link')
    if os.path.isdir(objects):
        # fetch uses a transport, never clone's local hardlink optimization.
        # Clear only owned single-link object files, after the process tree drains.
        for directory, dirs, files in os.walk(objects, followlinks=False):
            for name in dirs + files:
                path = os.path.join(directory, name)
                if store.reparse(path):
                    raise ValueError('Git preparation object path must not be a link')
                info = os.lstat(path)
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise RuntimeError('shared Git object attributes cannot be changed')
                    if not info.st_mode & stat.S_IWRITE:
                        os.chmod(path, info.st_mode | stat.S_IWRITE)
    store.remove_directory(workspace)
    if 'externalParent' in owner:
        os.rmdir(owner['externalParent'])  # Refuse unknown sibling payloads.


def _repository_size(repository):
    total = 0
    for directory, dirs, files in os.walk(repository, followlinks=False):
        for name in dirs + files:
            path = os.path.join(directory, name)
            try:
                if store.reparse(path):
                    raise ValueError('Git repository contains a filesystem link')
                if name in files:
                    total += os.path.getsize(path)
                    if total > MAX_REPOSITORY_BYTES:
                        raise PackageQueryError('ERR_DSH_GIT_SIZE', 'Git repository exceeds the preparation byte limit')
            except FileNotFoundError:
                pass  # Git atomically renames/removes transient lock/pack files.
    return total


def _safe_diagnostic(text, source, workspace):
    text = text.replace(source['repository'], source['publicRepository']).replace(workspace, '<git-source>')
    def clean(match):
        try:
            return public_repository(match[0])
        except ValueError:
            return '<repository>'
    return re.sub(r'(?:https?|ssh|git|file)://[^\s\'"<>]+', clean, text)


def _git_path(path):
    if os.name != 'nt':
        return path
    # Git's repository discovery/chdir still has MAX_PATH boundaries even
    # with core.longpaths. Resolve an existing owned path using a Win7 API.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0)
    kernel.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    kernel.GetShortPathNameW.restype = ctypes.c_ulong
    size = kernel.GetShortPathNameW(path, None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size)
    if not kernel.GetShortPathNameW(path, buffer, size):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def _git(executable, workspace, source, args, archive=None):
    repository = os.path.join(workspace, 'repository')
    hooks = _git_path(os.path.join(workspace, 'hooks'))
    env = dict(os.environ, LC_ALL='C', GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
        GIT_ASKPASS='', SSH_ASKPASS='', SSH_ASKPASS_REQUIRE='never')
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
            'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR', 'GIT_CONFIG_PARAMETERS',
            'GIT_CONFIG_COUNT'):
        env.pop(name, None)
    command = [executable, '-c', 'core.hooksPath=' + hooks, '-c', 'core.askPass=',
        '-c', 'protocol.file.allow=always', '-c', 'core.autocrlf=false', '-c', 'core.longpaths=true',
        '--git-dir=' + _git_path(repository)] + args
    process = subprocess.Popen(command, cwd=_git_path(workspace), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    output, error, failures = bytearray(), bytearray(), []
    exceeded = threading.Event()
    def stderr():
        while True:
            data = process.stderr.read1(65536)
            if not data:
                return
            error.extend(data)
            del error[:-16384]
    def stdout():
        try:
            target = gzip.open(archive, 'wb') if archive is not None else None
            size = 0
            try:
                while True:
                    data = process.stdout.read1(65536)
                    if not data:
                        return
                    size += len(data)
                    if size > (MAX_ARCHIVE_BYTES if target is not None else 65536):
                        exceeded.set()
                        process.kill()
                        return
                    if target is not None:
                        target.write(data)
                    else:
                        output.extend(data)
            finally:
                if target is not None:
                    target.close()
        except BaseException as failure:
            failures.append(failure)
            exceeded.set()
            process.kill()
    readers = [threading.Thread(target=stdout, daemon=True), threading.Thread(target=stderr, daemon=True)]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + GIT_TIMEOUT
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise PackageQueryError('ERR_DSH_GIT_TIMEOUT', 'Git source preparation timed out')
            _repository_size(repository)
            if exceeded.is_set():
                break
            time.sleep(.025)
        process.wait()
        if failures:
            raise failures[0]
        if exceeded.is_set():
            # A transport/helper may still hold inherited pipes. The outer
            # captured owner drains its entire tree before workspace cleanup.
            raise PackageQueryError('ERR_DSH_GIT_SIZE', 'Git source output exceeds the preparation byte limit')
        for reader in readers:
            reader.join(timeout=2)
        if any(reader.is_alive() for reader in readers):
            raise PackageQueryError('ERR_DSH_GIT_DRAIN', 'Git source output did not drain')
        _repository_size(repository)
        if process.returncode:
            detail = _safe_diagnostic(error.decode('utf-8', errors='replace'), source, workspace)
            raise PackageQueryError('ERR_DSH_GIT_SOURCE', 'Git source operation failed (' + str(process.returncode) + '): ' + detail)
        return bytes(output).decode('utf-8', errors='replace').strip()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        # On interrupted fetches the outer captured owner drains all descendants.
        for stream in (process.stdout, process.stderr):
            if not any(reader.is_alive() for reader in readers):
                stream.close()


def publish_git(directory, spec, output, workspace):
    _owned_workspace(workspace)
    source = git_source(spec)
    executable = shutil.which('git')
    if executable is None:
        raise PackageQueryError('ERR_DSH_GIT_MISSING', 'Git is required for Git package sources')
    hooks = os.path.join(workspace, 'hooks')
    os.mkdir(hooks)
    repository = os.path.join(workspace, 'repository')
    os.mkdir(repository)
    _git(executable, workspace, source, ['init', '--bare', '--template=' + _git_path(hooks)])
    _git(executable, workspace, source, ['remote', 'add', 'origin', source['repository']])
    print('Fetching Git source', flush=True)
    _git(executable, workspace, source, ['fetch', '--depth=1', '--filter=blob:none',
        '--no-tags', '--no-recurse-submodules', '--', 'origin', source['ref']])
    commit = _git(executable, workspace, source, ['rev-parse', '--verify', 'FETCH_HEAD^{commit}'])
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or re.fullmatch(r'[0-9a-f]{40}', source['ref']) and commit != source['ref']:
        raise PackageQueryError('ERR_DSH_GIT_IDENTITY', 'Git returned a different commit from the requested source')
    print('Archiving Git commit ' + commit, flush=True)
    archive = os.path.join(workspace, 'source.tgz')
    tree = commit + (':' + source['directory'] if source['directory'] else '')
    _git(executable, workspace, source, ['archive', '--format=tar', '--prefix=package/', tree], archive)
    with tempfile.TemporaryDirectory(prefix='source-', dir=workspace) as stage:
        unpack_tarball(archive, stage)
        manifest = publish_local(directory, stage, output)
    receipt = os.path.join(output, 'prepared.json')
    with open(receipt, encoding='utf-8') as stream:
        value = json.load(stream)
    value.update(formatVersion=3, git=dict(repository=source['publicRepository'], commit=commit, directory=source['directory']))
    store.atomic_bytes(receipt, store.json_bytes(value))
    return manifest
