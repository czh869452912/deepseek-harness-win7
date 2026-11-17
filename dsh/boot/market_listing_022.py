"""Current market annotation over shared pure compatibility/install helpers."""
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility
from dsh.boot.plugin_install_spec import pinned_git_origin
from dsh.boot.semver import parse


def install_target(name, version):
    source = version['source']
    if source['type'] == 'npm':
        target = dict(spec=name+'@'+version['version'])
        if 'registry' in source:
            target['registry'] = source['registry']
        return target
    repository = source['url']
    if not repository.endswith('.git'):
        repository += '.git'
    return dict(spec='git+'+repository+'#'+source['commit']+('' if 'path' not in source else '&path:/'+source['path']))


def prerelease(value):
    try: return parse(value).pre
    except ValueError: return None


def installation_of(bundle, version):
    if bundle is None or (not bundle['installed'] and bundle['availability'] != 'installation'):
        return dict(status='not-installed')
    if not bundle['installed']:
        return dict(status='provided', **({} if 'version' not in bundle else dict(installedVersion=bundle['version'])))
    if 'version' not in bundle:
        return dict(status='different-version')
    installed = bundle['version']
    if installed == version:
        return dict(status='installed', installedVersion=installed)
    try: parsed = parse(installed)
    except ValueError: parsed = None
    newer = parsed is not None and parse(version) > parsed
    return dict(status='update-available' if newer else 'different-version', installedVersion=installed)


def listing_of(plugin, bundles, exemptions, runtime_version):
    bundle = next((bundle for bundle in bundles if bundle['name'] == plugin['name']), None)
    origin = pinned_git_origin(bundle['source']) if bundle is not None and bundle.get('update') == 'git' and 'source' in bundle else None
    installed = None if bundle is None else bundle.get('version')
    versions = []
    for version in plugin['versions']:
        target = install_target(plugin['name'], version)
        update = (origin is not None and installed is not None and parse(version['version']) > parse(installed)
                  and pinned_git_origin(target['spec']) == origin)
        manifest = dict(name=plugin['name'], version=version['version'])
        if 'dsh' in version['engines']:
            manifest['engines'] = dict(dsh=version['engines']['dsh'])
        issue = evaluate_plugin_compatibility(manifest, exemptions, runtime_version)
        compatibility = dict(compatible=True) if issue is None else dict(compatible=False,
            runtimeVersion=issue['runtimeVersion'], requirements=issue['requirements'], exempted=issue['exempted'])
        versions.append(dict(version, install=target, compatibility=compatibility, update=update))
    stable = any(prerelease(version['version']) is None for version in plugin['versions'])
    default = next((version['version'] for version in versions if version['compatibility']['compatible']
                    and (not stable or prerelease(version['version']) is None)), None)
    result = dict(plugin, versions=versions, installation=installation_of(bundle, default or versions[0]['version']))
    if default is not None:
        result['defaultVersion'] = default
    return result
