"""Read-only package identities and official install targets, without imports."""
import glob
import json
import os
from pathlib import Path

from dsh.boot.plugin_install_spec import InvalidInstallSpecError, parse_install_spec, pinned_git_origin
from dsh.boot.profile import read_profile_manifest, bundle_patch_paths
from dsh.boot.runtime_resolution import _field, _installation_resolver
from dsh.boot.semver import parse


OFFICIAL_DATA = json.loads(Path(__file__).with_name('official_bundles_current.json').read_text(encoding='utf-8'))
OPTIONAL_BUNDLES = OFFICIAL_DATA['optionalBundles']
OFFICIAL_CATALOG = OFFICIAL_DATA['catalog']


def bundle_selection(manifest):
    return _field(_field(_field(manifest, 'dsh'), 'profile'), 'bundles') or []


def bundle_directory(name, directory, anchor):
    # Only the canonical Python launcher owns the flattened Portable graph.
    # A profile below this checkout must not inherit ambient workspace copies.
    from dsh.boot.profile_boot import _CANDIDATE_ANCHORS
    options = dict(installAnchor=anchor)
    if os.path.abspath(anchor) in _CANDIDATE_ANCHORS:
        options['installationLayout'] = str(Path(__file__).resolve().parents[2])
    resolve_installation = _installation_resolver(options)
    from dsh.boot.runtime_resolution import native_package_dir
    package = resolve_installation(anchor, name) or native_package_dir(os.path.join(directory, 'package.json'), name)
    if package is None:
        raise RuntimeError('dsh: cannot resolve profile bundle '+json.dumps(name)+' from the dsh installation or '+directory)
    return package


def bundle_manifest(name, directory, anchor):
    package = bundle_directory(name, directory, anchor)
    manifest = read_profile_manifest('dsh', package)
    bundle = _field(_field(manifest, 'dsh'), 'bundle')
    return manifest if isinstance(bundle, dict) and 'patch' in bundle else None


def official_bundle_install_target(name, install_anchor, version):
    def read(path):
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            return json.load(stream)
    anchor = os.path.realpath(install_anchor)
    installation = read(anchor)
    source = installation.get('name') == '@deepseek-ai/dsh' and any(
        value.startswith('workspace:') for value in installation.get('dependencies', {}).values())
    if not source:
        return dict(spec=name+'@'+version, version=version)
    root = os.path.abspath(os.path.join(os.path.dirname(anchor), '../..'))
    root_manifest = os.path.join(root, 'package.json')
    if (anchor != os.path.join(root, 'apps', 'cli', 'package.json')
            or not os.path.exists(root_manifest) or read(root_manifest).get('name') != '@deepseek-ai/dsh-root'):
        raise RuntimeError('Official bundle '+name+': source DSH installation '+anchor+' requires its complete workspace checkout')
    matches = [(file, read(file)) for file in glob.glob(os.path.join(root, 'packages', '*', '*', 'package.json'))]
    matches = [(file, manifest) for file, manifest in matches if manifest.get('name') == name]
    if len(matches) != 1:
        raise RuntimeError('Official bundle '+name+': expected one workspace package in '+root+', found '+str(len(matches))+'; restore the checkout and run pnpm install')
    file, manifest = matches[0]
    directory = os.path.realpath(os.path.dirname(file))
    bundle = _field(manifest.get('dsh'), 'bundle')
    if manifest.get('version') != version or manifest.get('private') is True or bundle is None:
        raise RuntimeError('Official bundle '+name+': '+file+' must declare a public bundle at DSH version '+version)
    main = os.path.abspath(os.path.join(directory, manifest['main'])) if isinstance(manifest.get('main'), str) else None
    if main is None or not os.path.isfile(main):
        raise RuntimeError('Official bundle '+name+': built runtime is missing in '+directory+'; run pnpm install and pnpm run build in '+root)
    for patch in bundle_patch_paths(directory, bundle):
        if not os.path.isfile(patch):
            raise RuntimeError('Official bundle '+name+': bundle patch '+patch+' is missing; restore the checkout')
    return dict(spec='link:'+directory, version=version)


def parsed_for_registry(spec):
    try:
        return parse_install_spec(spec)
    except InvalidInstallSpecError:
        return dict(kind='registry', spec=spec, name=spec)


def update_refusal(bundle, name):
    if (bundle is None or not bundle.get('installed') or bundle.get('availability') != 'profile'
            or bundle.get('official') or 'source' not in bundle):
        return name+' is not a third-party package installed in this profile'
    if 'readOnlyReason' in bundle:
        return bundle['name']+' carries plugin management and cannot be removed'
    installed = bundle.get('version')
    try:
        parse(installed)
    except ValueError:
        return bundle['name']+' declares no semver version'
    origin = pinned_git_origin(bundle['source'])
    if origin is not None:
        return dict(kind='git', bundle=bundle, installed=installed, source=bundle['source'], origin=origin)
    parsed = parsed_for_registry(bundle['source'])
    if parsed['kind'] != 'registry' or parsed['name'] != bundle['name'] or ':' in parsed.get('range', ''):
        return bundle['name']+' is installed neither from a registry under its own name nor from a Git commit'
    return dict(kind='registry', bundle=bundle, installed=installed, parsed=parsed)
