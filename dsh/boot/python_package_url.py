"""Publish an explicit remote tarball without inventing registry SRI evidence."""
import os
import shutil
import tempfile

from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.python_package_acquire import _compatible, NativePackageRefused
from dsh.boot.python_package_tarball import downloaded_url_tarball, unpack_tarball
from dsh.boot.python_plugins import validate_package, atomic_bytes, json_bytes


def publish_url(directory, spec, output):
    parsed = parse_install_spec(spec)
    if parsed['kind'] != 'tarball' or 'path' in parsed:
        raise ValueError('an explicit remote tarball source is required')
    with downloaded_url_tarball(parsed['spec']) as (archive, acquisition):
        with tempfile.TemporaryDirectory(prefix='verify-url-', dir=os.path.dirname(output)) as stage:
            unpack_tarball(archive, stage)
            try:
                manifest = validate_package(stage)
            except ValueError as error:
                raise NativePackageRefused('ERR_DSH_PACKAGE_VALIDATION', str(error).replace(stage, '<package>')) from None
            _compatible(manifest, read_profile_version_exemptions(directory))
        shutil.copyfile(archive, os.path.join(output, 'package.tgz'))
        atomic_bytes(os.path.join(output, 'prepared.json'), json_bytes(dict(
            formatVersion=4, manifest=manifest, acquisition=acquisition)))
        return manifest
