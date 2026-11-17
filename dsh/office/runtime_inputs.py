"""Verify an offline Office runtime inventory prepared by the release builder."""
import hashlib
import json
from pathlib import Path
import stat

from .errors import OfficeKitError


# Filled only after recording independently acquired binary/license identities.
MANIFESTS = {
    'x64': '5bee4d6cf0f91c5ee144f1baa48a2802422eed3ce42810838f18366728fa988b',
    'x86': '43c9b9e30992ab1b828894ae7042ef4ae4c95cdc713be4f920f9b2c9956c3e79',
}


def _plain_file(root, relative):
    path = Path(relative)
    if relative.startswith('/') or path.is_absolute() or '..' in path.parts or ':' in relative or '\\' in relative:
        raise ValueError('Invalid Office runtime resource path.')
    current = root
    for part in path.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Aliased Office runtime resource.')
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Office runtime resource is not a regular file.')
    return current


def verify_installed_runtime(root, architecture):
    root = Path(root).absolute()
    # Reject a linked runtime root as well as linked members.
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Aliased Office runtime root.')
    raw = _plain_file(root, 'runtime.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFESTS.get(architecture):
        raise OfficeKitError('unavailable', 'Office runtime inventory is not approved.')
    manifest = json.loads(raw)
    if manifest.get('format') != 'dsh-office-runtime@1' or manifest.get('architecture') != architecture:
        raise ValueError('Office runtime inventory differs.')
    resources = manifest['resources']
    for name, expected in resources.items():
        path = _plain_file(root, name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(data)
        if path.stat().st_size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
            raise OfficeKitError('unavailable', 'Office runtime resource differs.')
    executable, package = manifest['executable'], manifest['package']
    if executable not in resources or package + '/package.json' not in resources:
        raise ValueError('Office runtime entry points are not owned.')
    return dict(executable=str(_plain_file(root, executable)), package=str(root / package))
