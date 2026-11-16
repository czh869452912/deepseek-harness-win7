"""Short-lived verified installed-file recovery, independent of the registry."""
import copy
from contextlib import contextmanager
import json
import os
import tempfile

from dsh.boot import python_plugins as store
from dsh.boot.profile import read_profile_manifest
from dsh.boot.python_plugin_versions import managed, owned_path

_OWNER = object()
ROOT = '.dsh-python-updates'


class InstalledPackageSnapshot:
    def __init__(self, directory, source, manifest, record, owner):
        if owner is not _OWNER:
            raise RuntimeError('installed snapshots require a verified owning scope')
        self.directory = os.path.normcase(os.path.realpath(directory))
        self.source = source
        self.manifest = copy.deepcopy(manifest)
        self._record_json = json.dumps(record, ensure_ascii=False)
        self.closed = False
        self.preserved = False

    def record_for(self, directory, source):
        if (self.closed or os.path.normcase(os.path.realpath(directory)) != self.directory
                or os.path.normcase(os.path.realpath(source)) != os.path.normcase(os.path.realpath(self.source))):
            raise RuntimeError('installed snapshot is expired or belongs to another source/profile')
        return json.loads(self._record_json)

    def preserve(self, reason):
        record = self.record_for(self.directory, self.source)
        # Failure to write a receipt must never delete the only recovery copy.
        self.preserved = True
        if store.file_hashes(self.source) != record['files']:
            raise RuntimeError('recovery snapshot changed before preservation')
        owner = os.path.dirname(self.source)
        receipt = dict(formatVersion=1, owner='native-package-update', profile=self.directory,
            reason=reason, reviewMilestone='next successful explicit recovery of this package', record=record)
        store.atomic_bytes(os.path.join(owner, 'recovery.json'), store.json_bytes(receipt))
        return owner


@contextmanager
def retained_installed_package(directory, name):
    target, record = managed(directory, name, read_profile_manifest('dsh', directory))
    root = owned_path(directory, ROOT)
    os.makedirs(root, exist_ok=True)
    snapshot, owned = None, None
    try:
        owned = tempfile.mkdtemp(prefix='update-', dir=root)
        source = os.path.join(owned, 'package')
        os.mkdir(source)
        store.copy_source(target, source)
        manifest = store.validate_package(source)
        if store.file_hashes(source) != record['files'] or manifest['name'] != name or manifest['version'] != record['version']:
            raise RuntimeError('installed package changed while retaining its recovery snapshot')
        snapshot = InstalledPackageSnapshot(directory, source, manifest, record, _OWNER)
        try:
            yield snapshot
        finally:
            snapshot.closed = True
    finally:
        if owned is not None and (snapshot is None or not snapshot.preserved):
            store.remove_directory(owned)
        try:
            os.rmdir(root)
        except OSError:
            pass  # Another update owns its own directory.


def restore_retained_package(directory, recovery, installation_anchor, lease=None, enabled=False):
    root = owned_path(directory, ROOT)
    relative = os.path.relpath(os.path.abspath(recovery), os.path.abspath(directory)).replace(os.sep, '/')
    owner = owned_path(directory, relative)
    if os.path.normcase(os.path.dirname(owner)) != os.path.normcase(root) or not os.path.basename(owner).startswith('update-'):
        raise ValueError('recovery must name an owned native update directory')
    source = owned_path(directory, relative + '/package')
    receipt = owned_path(directory, relative + '/recovery.json')
    if set(os.listdir(owner)) != {'package', 'recovery.json'} or os.path.getsize(receipt) > 1024 * 1024:
        raise ValueError('recovery directory contains unknown assets or an oversized receipt')
    with open(receipt, encoding='utf-8') as stream:
        value = json.load(stream)
    if (not isinstance(value, dict) or set(value) != {'formatVersion', 'owner', 'profile', 'reason', 'reviewMilestone', 'record'}
            or type(value['formatVersion']) is not int or value['formatVersion'] != 1
            or value['owner'] != 'native-package-update' or value['profile'] != os.path.normcase(os.path.realpath(directory))):
        raise ValueError('invalid native update recovery receipt')
    record = value['record']
    manifest = store.validate_package(source)
    if store.file_hashes(source) != record['files'] or manifest['version'] != record['version']:
        raise ValueError('retained recovery package differs from its installed-file record')
    snapshot = InstalledPackageSnapshot(directory, source, manifest, record, _OWNER)
    try:
        name = store.install(directory, source, installation_anchor, lease=lease, enabled=enabled, _snapshot=snapshot)
    finally:
        snapshot.closed = True
    store.remove_directory(owner)
    try:
        os.rmdir(root)
    except OSError:
        pass
    return name
