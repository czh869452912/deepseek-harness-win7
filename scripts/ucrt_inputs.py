"""Pinned Microsoft SDK app-local UCRT inputs; native Win7 execution is deferred."""
import hashlib
import json
from pathlib import Path
import shutil


MANIFEST_SHA256 = '632086f43adc87c504808fe3d94b6adf8e743388749426ba25b257a6c0f67380'


def _plain_file(path, root):
    for selected in (path,) + tuple(path.parents):
        metadata = selected.lstat()
        if selected.is_symlink() or getattr(metadata, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Aliased UCRT input: ' + str(selected))
        if selected == root:
            break
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('UCRT input must be a private regular file: ' + str(path))
    return path.read_bytes()


def verify_pinned_ucrt(root):
    root = Path(root).absolute()
    directory = root / 'vendor/ucrt'
    raw = _plain_file(directory / 'ucrt-input.json', root)
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError('Pinned UCRT manifest changed')
    manifest = json.loads(raw.decode('utf-8'))
    rows = manifest['files']
    names = [row['name'] for row in rows]
    if len(rows) != 41 or len(set(names)) != 41 or 'ucrtbase.dll' not in names:
        raise ValueError('Incomplete UCRT file inventory')
    for row in rows:
        name = row['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Invalid UCRT file path')
        raw = _plain_file(directory / 'x64' / name, root)
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Pinned UCRT binary changed: ' + name)
    for name, expected in (('SDK-LICENSE.rtf', manifest['licenseSha256']), ('REDIST.html', manifest['redistSha256'])):
        if hashlib.sha256(_plain_file(directory / name, root)).hexdigest() != expected:
            raise ValueError('Pinned UCRT license record changed: ' + name)
    return manifest


def bundle_ucrt(root, destination):
    manifest = verify_pinned_ucrt(root)
    directory = Path(root) / 'vendor/ucrt'
    destination = Path(destination)
    for row in manifest['files']:
        shutil.copyfile(str(directory / 'x64' / row['name']), str(destination / row['name']))
    for name, target in (('ucrt-input.json', 'ucrt-input.json'),
                         ('SDK-LICENSE.rtf', 'UCRT-LICENSE.rtf'), ('REDIST.html', 'UCRT-REDIST.html')):
        shutil.copyfile(str(directory / name), str(destination / target))
    validate_bundled_ucrt(destination, manifest)
    return manifest


def validate_bundled_ucrt(directory, manifest):
    """Reject missing, relocated or modified inputs in an extracted candidate."""
    directory = Path(directory)
    raw = _plain_file(directory / 'ucrt-input.json', directory)
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256 or json.loads(raw.decode('utf-8')) != manifest:
        raise ValueError('Extracted UCRT manifest changed')
    for row in manifest['files']:
        raw = _plain_file(directory / row['name'], directory)
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Extracted UCRT binary changed: ' + row['name'])
    for name, expected in (('UCRT-LICENSE.rtf', manifest['licenseSha256']), ('UCRT-REDIST.html', manifest['redistSha256'])):
        if hashlib.sha256(_plain_file(directory / name, directory)).hexdigest() != expected:
            raise ValueError('Extracted UCRT license record changed: ' + name)
    return manifest
