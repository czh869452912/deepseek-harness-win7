"""Snapshot reviewed local native sources into a bounded private publication."""
import hashlib
import os
import tarfile
import tempfile

from dsh.boot import python_plugins as store
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.python_package_acquire import _compatible, NativePackageRefused


def archive_record(path):
    digest, size = hashlib.sha256(), 0
    with open(path, 'rb') as stream:
        while True:
            data = stream.read(65536)
            if not data:
                break
            size += len(data)
            if size > store.MAX_BYTES:
                raise ValueError('prepared local archive exceeds byte limit')
            digest.update(data)
    return dict(sha256=digest.hexdigest(), bytes=size)


def publish_local(directory, source, output):
    with tempfile.TemporaryDirectory(prefix='local-', dir=os.path.dirname(output)) as stage:
        try:
            store.copy_source(source, stage)
            manifest = store.validate_package(stage)
            _compatible(manifest, read_profile_version_exemptions(directory))
        except NativePackageRefused:
            raise
        except ValueError as error:
            raise NativePackageRefused('ERR_DSH_PACKAGE_VALIDATION', str(error).replace(stage, '<package>')) from None
        files = store.file_hashes(stage)
        archive = os.path.join(output, 'package.tgz')
        with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as tar:
            for relative, path in store.regular_tree(stage):
                member = tarfile.TarInfo('package/' + relative)
                member.size = os.path.getsize(path)
                with open(path, 'rb') as stream:
                    tar.addfile(member, stream)
        value = dict(formatVersion=2, manifest=manifest, acquisition=None, files=files, archive=archive_record(archive))
        store.atomic_bytes(os.path.join(output, 'prepared.json'), store.json_bytes(value))
        return manifest
