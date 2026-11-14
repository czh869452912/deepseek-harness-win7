"""Compatibility decisions at DSH-owned composition boundaries, before import."""
import copy
import errno
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname
import yaml
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility, plugin_compatibility_warning
from dsh.boot.profile_compatibility import read_profile_compatibility
from dsh.boot.plugin_packages import bare_package_name
from dsh.cordis.loader import apply_entry_patches
_MISSING = object()


def _field(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _path(value):
    parsed = urlparse(value)
    if parsed.scheme == 'file':
        path = url2pathname(parsed.path)
        return ('//'+parsed.netloc+path) if parsed.netloc else path
    if parsed.scheme and not os.path.isabs(value):
        raise ValueError('Plugin metadata requires a local file URL')
    return value


def _directory(base):
    path = _path(base)
    return path if base.endswith(('/', '\\')) else os.path.dirname(path)


def _read_manifest(filename):
    with open(filename, 'r', encoding='utf-8', errors='replace') as stream:
        return json.load(stream)


def _bare_name(name):
    return bare_package_name(name)


def _alias(name, base):
    """Read package imports metadata without evaluating an entry or parent package."""
    directory = _directory(base)
    while True:
        try:
            manifest = _read_manifest(os.path.join(directory, 'package.json'))
        except FileNotFoundError:
            parent = os.path.dirname(directory)
            if parent == directory:
                raise ValueError('Package imports alias '+name+' cannot be resolved')
            directory = parent
            continue
        imports = manifest.get('imports', {}) if isinstance(manifest, dict) else {}
        target = imports.get(name) if isinstance(imports, dict) else None
        if isinstance(target, dict):
            target = next((v for k, v in target.items() if k in ('node', 'import', 'default')), None)
        if not isinstance(target, str):
            raise ValueError('Package imports alias '+name+' cannot be resolved')
        return os.path.join(directory, target) if target.startswith('./') else target


def _manifest_of(ctx, name, base):
    if name.startswith('cordis:'):
        return _MISSING
    specifier = _alias(name, base) if name.startswith('#') else name
    packages = ctx.get('pluginPackages')
    if packages is not None:
        package_of = getattr(packages, 'packageOf', None) or getattr(packages, 'package_of')
        package = package_of(specifier, base)
        if package is not None:
            return _read_manifest(_field(package, 'manifestPath'))
    bare = _bare_name(specifier)
    if bare is not None and packages is None:
        directory = _directory(base)
        while True:
            filename = os.path.join(directory, 'node_modules', bare, 'package.json')
            if os.path.exists(filename):
                return _read_manifest(filename)
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
    if not os.path.isabs(specifier) and not specifier.startswith(('.', 'file:')):
        return _MISSING
    requested = specifier if os.path.isabs(specifier) else _path(urljoin(base, specifier))
    # Python's explicit export suffix is host syntax, not part of the filename.
    requested = re.sub(r'(?<=\.py):[A-Za-z_][A-Za-z_0-9]*$', '', requested)
    try:
        filename = Path(requested).resolve(strict=True)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.EISDIR):
            return _MISSING
        raise
    directory = str(filename.parent)
    while True:
        try:
            return _read_manifest(os.path.join(directory, 'package.json'))
        except FileNotFoundError:
            parent = os.path.dirname(directory)
            if parent == directory:
                return _MISSING
            directory = parent


def _patch_warning(ctx):
    def warn(message, *args):
        for arg in args:
            message = message.replace('%C', json.dumps(arg, ensure_ascii=False, separators=(',', ':')), 1)
        ctx.logger.warn(message)
    return warn


def prepare_profile_entries(ctx, entries, parent_url, bin_name='dsh'):
    rows = copy.deepcopy(entries)
    profile = ctx.get('profileContext')
    if profile is None:
        return rows
    if parent_url is None:
        raise ValueError('Profile compatibility preflight requires a resolution base')
    compatibility = read_profile_compatibility(_field(profile, 'dir'))
    for warning in compatibility['warnings']:
        sys.stderr.write(warning+'\n')
    includes = set()
    def denial(row, base):
        try:
            manifest = _manifest_of(ctx, row['name'], base)
            if manifest is _MISSING:
                return None
            issue = evaluate_plugin_compatibility(manifest, compatibility['exemptions'])
            return None if issue is None or issue['exempted'] else plugin_compatibility_warning(issue)
        except Exception as error:
            return 'its declared dsh requirements cannot be validated: '+str(error)
    def deny(row, reason):
        row['disabled'] = True
        if row.get('group'):
            row['group'] = False
        label = 'row '+json.dumps(row['id'], ensure_ascii=False) if isinstance(row.get('id'), str) else row['name']
        sys.stderr.write(bin_name+': disabling profile plugin '+label+': '+reason+'\n')
    def included_conflicts(row, base):
        config = row.get('config')
        path = config.get('path') if isinstance(config, dict) else None
        if not isinstance(path, str) or os.path.splitext(path)[1] not in ('.json', '.yaml', '.yml'):
            return None
        requested = path if os.path.isabs(path) else _path(urljoin(base, path))
        filename = os.path.realpath(requested) if os.path.exists(requested) else requested
        if filename in includes:
            return None
        includes.add(filename)
        try:
            try:
                with open(filename, 'r', encoding='utf-8') as stream:
                    data = yaml.safe_load(stream)
            except FileNotFoundError:
                if 'initial' not in config:
                    return None
                data = config['initial']
            except Exception:
                return None
            if not isinstance(data, list):
                return None
            children = apply_entry_patches(data, config.get('patches'), _patch_warning(ctx))
            if check(children, Path(filename).as_uri()):
                return 'its included file '+filename+' reaches an incompatible plugin, and that file is never rewritten'
            return None
        finally:
            includes.remove(filename)
    def check(children, base):
        blocked = False
        for row in children:
            if row.get('disabled') is True and not row.get('group'):
                continue
            reason = denial(row, base)
            if reason is not None:
                deny(row, reason); blocked = True
                continue
            if (row.get('group') is True or row['name'] in ('cordis:group', '@deepseek-ai/cordis-plugin-group')) and isinstance(row.get('config'), list):
                if check(row['config'], base):
                    blocked = True
            if row['name'] in ('cordis:include', '@deepseek-ai/cordis-plugin-include'):
                reason = included_conflicts(row, base)
                if reason is not None:
                    deny(row, reason); blocked = True
        return blocked
    check(rows, parent_url)
    return rows


def prepare_profile_patches(ctx, patches, parent_url, bin_name='dsh'):
    if ctx.get('profileContext') is None:
        return patches
    entries = apply_entry_patches([], patches, _patch_warning(ctx))
    rows = prepare_profile_entries(ctx, entries, parent_url, bin_name)
    return [] if not rows else [dict(insert=rows)]


prepareProfileEntries = prepare_profile_entries
prepareProfilePatches = prepare_profile_patches
