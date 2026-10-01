"""Profile-local package management for the canonical launcher."""
import json
import os
import re
import shutil
import subprocess
import sys

from dsh.boot.profile import (DEFAULT_PROFILE_BUNDLES, PROFILE_TEMPLATES,
                              init_profile, read_profile_manifest, resolve_bundle_dir,
                              resolve_profile_dir, write_profile_manifest)
from dsh.boot.profile_boot import INSTALL_ANCHOR


def anchor_path_spec(argument, cwd):
    match = re.fullmatch(r"((?:file|link):)?(\.{1,2}(?:[/\\].*)?)", argument)
    return (match.group(1) or "") + os.path.abspath(os.path.join(cwd, match.group(2))) if match else argument


def _exports_patch(name, directory):
    try:
        resolved = resolve_bundle_dir("dsh", name, INSTALL_ANCHOR, directory)
        return read_profile_manifest("dsh", resolved).get("dsh", {}).get("bundle", {}).get("patch") is not None
    except RuntimeError:
        return False


def reconcile_plugins(before, directory):
    after = read_profile_manifest("dsh", directory)
    old_dependencies = set(before.get("dependencies", {}))
    dependencies = after.get("dependencies", {})
    profile = after.setdefault("dsh", {}).setdefault("profile", {})
    bundles = profile.setdefault("bundles", [])
    exported = {name: _exports_patch(name, directory) for name in dependencies}
    for name in dependencies:
        if exported[name] and name not in bundles:
            bundles.append(name)
        elif not exported[name] and name not in old_dependencies:
            sys.stderr.write("dsh: warning: {} declares no dsh.bundle; installed as a plain dependency\n".format(name))
    bundles[:] = [name for name in bundles if
                  name not in old_dependencies | set(dependencies) or exported.get(name, False)]
    write_profile_manifest(directory, after)


def run_plugin(profile, args):
    if args and args[0] == 'pack':
        if len(args) != 3:
            raise ValueError('use pack <Python project> <output.zip>')
        from dsh.boot.python_plugin_export import pack_project
        name = pack_project(args[1], args[2])
        sys.stdout.write('dsh: packed Python plugin {}\n'.format(name))
        return 0
    directory = resolve_profile_dir(profile)
    from dsh.boot.python_plugins import install, uninstall
    from dsh.boot.python_plugin_versions import upgrade, rollback, versions
    from dsh.boot.profile_lease import ProfileLease
    if len(args) == 2 and args[0] in ("add", "upgrade") and (
        os.path.exists(args[1]) or args[1].lower().endswith(".zip") or args[1].startswith(("./", "../", ".\\", "..\\"))
    ):
        if args[0] == 'upgrade' and not os.path.isfile(os.path.join(directory, 'package.json')):
            raise ValueError('upgrade requires an existing profile and managed Python plugin')
        if not os.path.isfile(os.path.join(directory, "package.json")):
            with ProfileLease(directory, exclusive=True):
                template = PROFILE_TEMPLATES.get(profile, {})
                init_profile(directory, template.get("bundles", DEFAULT_PROFILE_BUNDLES), template.get("patchReload", "live"))
        name = (install if args[0] == 'add' else upgrade)(directory, args[1], INSTALL_ANCHOR)
        sys.stdout.write("dsh: {} Python plugin {} into {}\n".format('installed' if args[0] == 'add' else 'upgraded', name, profile))
        return 0
    if args and args[0] in ('rollback', 'versions'):
        if len(args) not in ((2, 3) if args[0] == 'rollback' else (2,)):
            raise ValueError('use rollback <package> [version] or versions <package>')
        if args[0] == 'versions':
            sys.stdout.write(json.dumps(versions(directory, args[1]), ensure_ascii=True, indent=2) + '\n')
        else:
            name = rollback(directory, args[1], args[2] if len(args) == 3 else None)
            sys.stdout.write('dsh: rolled back Python plugin {} in {}\n'.format(name, profile))
        return 0
    if len(args) == 2 and args[0] in ("remove", "rm") and os.path.isfile(os.path.join(directory, "package.json")):
        manifest = read_profile_manifest("dsh", directory)
        if args[1] in manifest.get("dsh", {}).get("pythonPlugins", {}):
            uninstall(directory, args[1])
            sys.stdout.write("dsh: removed Python plugin {} from {}\n".format(args[1], profile))
            return 0
    with ProfileLease(directory, exclusive=True):
        return run_pnpm(profile, directory, args)


def run_pnpm(profile, directory, args):
    if not os.path.isfile(os.path.join(directory, "package.json")):
        template = PROFILE_TEMPLATES.get(profile, {})
        init_profile(directory, template.get("bundles", DEFAULT_PROFILE_BUNDLES), template.get("patchReload", "live"))
    before = read_profile_manifest("dsh", directory)
    if before.get("dsh", {}).get("pythonPlugins") and (not args or args[0] not in ("list", "ls", "why", "outdated")):
        raise ValueError("pnpm mutations cannot manage this profile's Python snapshots; use Python add/upgrade/rollback/remove commands")
    executable = shutil.which("pnpm")
    if executable is None:
        sys.stderr.write("dsh: pnpm not found on PATH; install pnpm to manage profile plugins\n")
        return 127
    # pnpm is a command shim on Windows; keep arguments as a sequence so
    # subprocess owns quoting instead of interpolating user input into a script.
    command = [executable] + [anchor_path_spec(arg, os.getcwd()) for arg in args]
    result = subprocess.run(command, cwd=directory)
    if result.returncode == 0:
        reconcile_plugins(before, directory)
    else:
        sys.stderr.write("dsh: pnpm failed in profile directory {}\n".format(directory))
    return result.returncode
