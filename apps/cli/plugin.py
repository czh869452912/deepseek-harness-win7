"""Profile-local package management for the canonical launcher."""
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
    directory = resolve_profile_dir(profile)
    if not os.path.isfile(os.path.join(directory, "package.json")):
        template = PROFILE_TEMPLATES.get(profile, {})
        init_profile(directory, template.get("bundles", DEFAULT_PROFILE_BUNDLES), template.get("patchReload", "live"))
    before = read_profile_manifest("dsh", directory)
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
