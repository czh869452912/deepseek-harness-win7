"""Stopped-profile native registry/Git commands for the canonical CLI."""
import asyncio
import os
import sys

from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.profile import DEFAULT_PROFILE_BUNDLES, PROFILE_TEMPLATES, init_profile
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package_prepare import prepared_registry_package, prepared_git_package, prepared_url_package
from dsh.boot.python_plugins import install
from dsh.boot.python_plugin_versions import upgrade


def native_package_command(profile, directory, args, installation_anchor):
    """Return None for existing local/ZIP commands; never fall back on failure."""
    if not args or args[0] not in ('add', 'upgrade') or '--sha256' in args:
        return None
    if len(args) < 2:
        raise ValueError('use add/upgrade <package spec> [--registry <URL>]')
    raw = args[1]
    # Preserve the established local/explicit-digest ZIP paths and diagnostics.
    if (os.path.exists(raw) or raw.lower().endswith(('.zip', '.tgz', '.tar.gz'))
            and not raw.lower().startswith(('https:', 'http:'))
            or raw.startswith(('./', '../', '.\\', '..\\'))):
        return None
    if raw.lower().startswith(('https:', 'http:')) and raw.split('#', 1)[0].split('?', 1)[0].lower().endswith('.zip'):
        return None
    parsed = parse_install_spec(raw)
    if parsed['kind'] not in ('registry', 'git', 'tarball') or 'path' in parsed:
        return None
    registry, index = None, 2
    while index < len(args):
        argument = args[index]
        if argument == '--registry' and index + 1 < len(args):
            index += 1
            value = args[index]
        elif argument.startswith('--registry='):
            value = argument[len('--registry='):]
        else:
            raise ValueError('use add/upgrade <package spec> [--registry <URL>]')
        if registry is not None or not value or value.startswith('-'):
            raise ValueError('native package command requires at most one nonempty registry URL')
        registry = value
        index += 1
    if args[0] == 'upgrade' and not os.path.isfile(os.path.join(directory, 'package.json')):
        raise ValueError('upgrade requires an existing profile and managed Python plugin')

    async def perform(lease):
        preparation = (prepared_git_package(directory, raw) if parsed['kind'] == 'git'
            else prepared_url_package(directory, raw) if parsed['kind'] == 'tarball'
            else prepared_registry_package(directory, raw, dict(registry=registry)))
        async with preparation as prepared:
            if prepared.candidate is None:
                sys.stderr.write(prepared.result['output'] + '\n')
                return prepared.result['exitCode'] or 1
            if not os.path.isfile(os.path.join(directory, 'package.json')):
                template = PROFILE_TEMPLATES.get(profile, {})
                init_profile(directory, template.get('bundles', DEFAULT_PROFILE_BUNDLES))
            candidate = prepared.candidate
            name = (install if args[0] == 'add' else upgrade)(directory, candidate.source,
                installation_anchor, candidate.acquisition, lease=lease)
            sys.stdout.write('dsh: {} Python plugin {} into {}\n'.format(
                'installed' if args[0] == 'add' else 'upgraded', name, profile))
            return 0

    with ProfileLease(directory, exclusive=True) as lease:
        return asyncio.run(perform(lease))
