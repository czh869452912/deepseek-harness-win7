"""Bind registry metadata, native ABI and original archive bytes before mutation."""
from contextlib import contextmanager
import tempfile
from types import SimpleNamespace

from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility,plugin_compatibility_warning
from dsh.boot.plugin_registry_policy import normalize_registry
from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.python_package import package_name
from dsh.boot.python_package_query import PackageQueryError,query_metadata,npm_configuration,package_registry,_public
from dsh.boot.python_package_tarball import downloaded_tarball,unpack_tarball
from dsh.boot.python_plugins import validate_package
from dsh.boot.semver import is_exact_version

ACQUISITION_FIELDS=['name','version','dsh','engines','peerDependencies','dist']


class NativePackageRefused(PackageQueryError):
    def __init__(self,code,message,incompatible=None):
        self.incompatible=incompatible
        super().__init__(code,message)


def _compatible(manifest,exemptions):
    issue=evaluate_plugin_compatibility(manifest,exemptions)
    if issue is not None and not issue['exempted']:
        raise NativePackageRefused('ERR_DSH_PLUGIN_INCOMPATIBLE',plugin_compatibility_warning(issue),[{key:value for key,value in issue.items() if key!='exempted'}])


@contextmanager
def acquired_registry_package(directory,spec,registry=None,env=None,exemptions=None):
    parsed=parse_install_spec(spec)
    if parsed['kind']!='registry' or parsed.get('range','').startswith('npm:'):
        raise NativePackageRefused('ERR_DSH_PACKAGE_SPEC','native package installation requires a registry identity under its own name')
    name=package_name(parsed['name'])
    selected = package_registry(npm_configuration(directory, env), name, registry)
    if registry is not None and selected != normalize_registry(registry):
        raise NativePackageRefused('ERR_DSH_REGISTRY_MISMATCH',
            'The configured package scope points to a different registry than the selected source')
    metadata=query_metadata(directory,spec,ACQUISITION_FIELDS,registry,env)
    if (not isinstance(metadata,dict) or metadata.get('name')!=name or not is_exact_version(metadata.get('version'))
            or is_exact_version(parsed.get('range')) and metadata['version']!=parsed['range']):
        raise NativePackageRefused('ERR_DSH_PACKAGE_IDENTITY','registry package identity differs from the requested package')
    version=metadata['version'];dsh=metadata.get('dsh')
    descriptor=dsh.get('python') if isinstance(dsh,dict) else None
    if not isinstance(descriptor,dict) or type(descriptor.get('apiVersion')) is not int or descriptor['apiVersion']!=1:
        raise NativePackageRefused('ERR_DSH_PYTHON_ABI',name+'@'+version+' does not include a compatible Python plugin')
    _compatible(metadata,exemptions)
    distribution=metadata.get('dist')
    if not isinstance(distribution,dict):raise NativePackageRefused('ERR_DSH_PACKAGE_ARTIFACT','registry package has no pinned archive')
    with downloaded_tarball(distribution.get('tarball'),distribution.get('integrity')) as (archive,record):
        record.update(name=name,version=version,registry=_public(selected))
        with tempfile.TemporaryDirectory(prefix='dsh-native-unpack-') as stage:
            unpack_tarball(archive,stage)
            try:manifest=validate_package(stage)
            except ValueError as error:raise NativePackageRefused('ERR_DSH_PACKAGE_VALIDATION',str(error).replace(stage,'<package>')) from None
            if manifest['name']!=name or manifest['version']!=version:
                raise NativePackageRefused('ERR_DSH_PACKAGE_IDENTITY','downloaded package identity differs from registry metadata')
            _compatible(manifest,exemptions)
            yield SimpleNamespace(manifest=manifest,source=archive,acquisition=record)
