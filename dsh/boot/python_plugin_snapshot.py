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

    def record_for(self, directory, source):
        if (self.closed or os.path.normcase(os.path.realpath(directory)) != self.directory
                or os.path.normcase(os.path.realpath(source)) != os.path.normcase(os.path.realpath(self.source))):
            raise RuntimeError('installed snapshot is expired or belongs to another source/profile')
        return json.loads(self._record_json)


@contextmanager
def retained_installed_package(directory, name):
    target, record = managed(directory, name, read_profile_manifest('dsh', directory))
    root = owned_path(directory, ROOT)
    os.makedirs(root, exist_ok=True)
    snapshot = None
    try:
        with tempfile.TemporaryDirectory(prefix='update-', dir=root) as owned:
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
        try:
            os.rmdir(root)
        except OSError:
            pass  # Another update owns its own directory.
