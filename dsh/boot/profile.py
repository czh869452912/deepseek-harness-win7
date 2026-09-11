"""
Profile discovery, initialization, and patch-layer composition for dsh launcher.
Matching reference/packages/boot/app-boot/src/profile.ts 1:1.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import json
import os
import re
import shutil
import stat
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
import urllib.parse

from dsh.cordis.loader import apply_entry_patches
from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.file_lock import with_file_lock


PROFILES_DIR = "profiles"
PROFILE_PATCH_FILENAME = "cordis.patch.yml"
PROFILE_MODULE_FALLBACK_DIR = ".dsh-module-fallback"

DEFAULT_PROFILE_BUNDLES: Tuple[str, ...] = ("@deepseek-ai/dsh-base",)
DEFAULT_PROFILE_PATCH_RELOAD = "live"

PROFILE_PATCH_TEMPLATE = """# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
"""

PROFILE_PNPM_WORKSPACE = """packages:
  - .

nodeLinker: hoisted
autoInstallPeers: false
"""

PROFILE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "acp": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-acp-app"],
        "patchReload": "startup",
    },
    "web": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"],
        "patchReload": "live",
    },
    "headless": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "patchReload": "startup",
    },
    "standard": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "patchReload": "startup",
    },
    "minimal": {
        "bundles": ["@deepseek-ai/dsh-sdk-minimal"],
        "patchReload": "startup",
    },
    "creative": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "patchReload": "startup",
    },
    "sdk": {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app"],
        "patchReload": "startup",
    },
    "sdk-minimal": {
        "bundles": ["@deepseek-ai/dsh-sdk-minimal"],
        "patchReload": "startup",
    },
}

INSTALLATION_OWNED_PROFILE_TUPLES: Dict[str, List[str]] = {
    "headless": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-headless"],
}


class ProfileLayer:
    """One resolved bundle layer of a profile."""

    def __init__(
        self,
        package_name: str,
        package_dir: str,
        patch_path: str,
        patches: List[Dict[str, Any]],
    ):
        self.packageName = package_name
        self.package_name = package_name
        self.packageDir = package_dir
        self.package_dir = package_dir
        self.patchPath = patch_path
        self.patch_path = patch_path
        self.patches = patches

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __repr__(self) -> str:
        return f"<ProfileLayer {self.packageName} dir={self.packageDir}>"


class Profile:
    """A loaded profile: resolved bundle layers plus user's patch layer."""

    def __init__(
        self,
        name: str,
        dir_path: str,
        layers: List[ProfileLayer],
        patch_path: str,
        patches: List[Dict[str, Any]],
        patch_reload: str = DEFAULT_PROFILE_PATCH_RELOAD,
    ):
        self.name = name
        self.dir = dir_path
        self.layers = layers
        self.patchPath = patch_path
        self.patch_path = patch_path
        self.patches = patches
        self.patchReload = patch_reload
        self.patch_reload = patch_reload

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __repr__(self) -> str:
        return f"<Profile {self.name} dir={self.dir} layers={len(self.layers)}>"


def path_to_file_url(path: str) -> str:
    """Convert absolute filesystem path to file:// URI matching Node pathToFileURL."""
    norm = os.path.abspath(path).replace("\\", "/")
    if not norm.startswith("/"):
        norm = "/" + norm
    return "file://" + urllib.parse.quote(norm, safe="/:")


def is_symlink_or_junction(path: str) -> bool:
    """Return True if path is a symlink or Windows directory junction."""
    try:
        st = os.lstat(path)
        if os.path.islink(path):
            return True
        reparse_tag = getattr(st, "st_reparse_tag", 0)
        mount_point_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
        return bool(reparse_tag and reparse_tag == mount_point_tag)
    except (OSError, ValueError):
        return False


def read_link(path: str) -> str:
    """Read symlink or junction target, stripping Windows NT path prefix."""
    target = os.readlink(path)
    if target.startswith("\\\\?\\"):
        target = target[4:]
    return target


def create_symlink(target: str, link: str) -> None:
    """Create directory junction or symlink compatible with Windows 7."""
    target_abs = os.path.abspath(target)
    link_abs = os.path.abspath(link)
    if sys.platform == "win32":
        try:
            import _winapi
            _winapi.CreateJunction(target_abs, link_abs)
            return
        except Exception:
            os.symlink(target_abs, link_abs, target_is_directory=os.path.isdir(target_abs))
    else:
        os.symlink(target_abs, link_abs)


def canonical_link_path(path: str) -> Optional[str]:
    """Resolve a link target without following the final path component."""
    try:
        parent = os.path.dirname(path)
        if not os.path.exists(parent):
            return None
        real_parent = os.path.realpath(parent)
        return os.path.normcase(os.path.normpath(os.path.join(real_parent, os.path.basename(path))))
    except Exception:
        return None


def symlink_points_to(link: str, target: str) -> bool:
    """Return whether a symlink or junction points at the same path as target."""
    try:
        actual = os.path.normpath(read_link(link))
        if not os.path.isabs(actual):
            actual = os.path.normpath(os.path.join(os.path.dirname(link), actual))
        canonical_actual = canonical_link_path(actual)
        canonical_target = canonical_link_path(os.path.abspath(target))
        return canonical_actual is not None and canonical_actual == canonical_target
    except Exception:
        return False


def is_packaged_executable() -> bool:
    """Return whether the process runs as a packaged binary."""
    return getattr(sys, "pkg", None) is not None or os.environ.get("DSH_TEST_PACKAGED") == "1"


def read_module_proxy_record(link: str) -> Optional[Dict[str, Any]]:
    """Read proxy metadata if present."""
    try:
        with open(os.path.join(link, "package.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def ensure_symlink(link: str, target: str) -> None:
    """Ensure link is a symlink/junction to target, replacing a wrong link or proxy."""
    if os.path.exists(link) or is_symlink_or_junction(link):
        if not is_symlink_or_junction(link):
            existing = read_module_proxy_record(link) if os.path.isdir(link) else None
            if not existing or "dsh" not in existing or "moduleFallback" not in existing.get("dsh", {}) or "targets" not in existing.get("dsh", {}).get("moduleFallback", {}):
                raise RuntimeError(
                    f"dsh: {link} exists and is not a symlink or dsh-managed module proxy; remove it so dsh can manage the installation fallback"
                )
            shutil.rmtree(link)
        else:
            if symlink_points_to(link, target):
                return
            os.unlink(link)
    os.makedirs(os.path.dirname(link), exist_ok=True)
    try:
        create_symlink(target, link)
    except OSError as error:
        if not (is_symlink_or_junction(link) and symlink_points_to(link, target)):
            raise error


def ensure_profile_symlink(link: str, target: str) -> None:
    """Add one profile-owned fallback link without replacing a pnpm-managed entry."""
    if os.path.exists(link) or is_symlink_or_junction(link):
        return
    ensure_symlink(link, target)


def owned_package_names(modules_dir: str) -> List[str]:
    """Package names represented by owned symlinks below one fallback node_modules."""
    if not os.path.exists(modules_dir):
        return []
    result: List[str] = []
    for name in os.listdir(modules_dir):
        full = os.path.join(modules_dir, name)
        if name.startswith("@") and os.path.isdir(full) and not is_symlink_or_junction(full):
            for child in os.listdir(full):
                child_full = os.path.join(full, child)
                if is_symlink_or_junction(child_full):
                    result.append(f"{name}/{child}")
        elif is_symlink_or_junction(full):
            result.append(name)
    return result


def remove_profile_symlink(profile_modules_dir: str, owned_modules_dir: str, package_name: str) -> None:
    """Remove an obsolete owned target and its profile projection when still connected."""
    owned_link = os.path.join(owned_modules_dir, package_name)
    profile_link = os.path.join(profile_modules_dir, package_name)
    try:
        if is_symlink_or_junction(profile_link) and symlink_points_to(profile_link, owned_link):
            os.unlink(profile_link)
    except OSError:
        pass
    try:
        if is_symlink_or_junction(owned_link):
            os.unlink(owned_link)
    except OSError:
        pass


def package_entry_from_package(
    package_name: str,
    package_dir: str,
    declared: Any,
    subpath: str,
) -> Optional[str]:
    """Resolve one available explicit package export under Node ESM import conditions."""
    specifier = package_name if subpath == "." else package_name + subpath[1:]

    def _resolve_target(exports_val: Any, sub: str) -> Optional[str]:
        if exports_val is None:
            return None
        if isinstance(exports_val, str):
            return exports_val if sub == "." else None
        if isinstance(exports_val, list):
            for item in exports_val:
                res = _resolve_target(item, sub)
                if res:
                    return res
            return None
        if isinstance(exports_val, dict):
            if sub in exports_val:
                target_val = exports_val[sub]
                if target_val is None:
                    raise RuntimeError(f"dsh: cannot resolve ESM export {specifier} from installed package {package_name}")
                if isinstance(target_val, str):
                    return target_val
                if isinstance(target_val, dict):
                    if "import" in target_val and target_val["import"] is None:
                        raise RuntimeError(f"dsh: cannot resolve ESM export {specifier} from installed package {package_name}")
                    for cond in ("import", "node", "default"):
                        if cond in target_val and isinstance(target_val[cond], str):
                            return target_val[cond]
                    return None
            if sub == ".":
                if "import" in exports_val and exports_val["import"] is None:
                    raise RuntimeError(f"dsh: cannot resolve ESM export {specifier} from installed package {package_name}")
                for cond in ("import", "node", "default"):
                    if cond in exports_val and isinstance(exports_val[cond], str):
                        return exports_val[cond]
        return None

    target = _resolve_target(declared, subpath)
    if target is None:
        return None

    entry = os.path.normpath(os.path.join(package_dir, target))
    rel_entry = os.path.relpath(entry, package_dir)
    if not target.startswith("./") or rel_entry.startswith(".."):
        raise RuntimeError(f"dsh: installed package {package_name} export {subpath} resolves outside its package: {target}")

    if os.path.isfile(entry):
        return path_to_file_url(entry)
    return None


def package_proxy_source(
    package_name: str,
    package_dir: str,
) -> Dict[str, Any]:
    """Resolve every explicit ESM runtime export that an out-of-tree plugin can import."""
    manifest_path = os.path.join(package_dir, "package.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"dsh: installed package {package_name} must declare a non-empty version")

    if "exports" not in manifest:
        raw_main = manifest.get("main")
        main = raw_main if isinstance(raw_main, str) and len(raw_main) > 0 else None
        main_entry = main if main else "index"
        entry_path = os.path.normpath(os.path.join(package_dir, main_entry))
        resolved = None
        for cand in [entry_path, entry_path + ".js", entry_path + ".mjs", os.path.join(entry_path, "index.js")]:
            if os.path.isfile(cand):
                resolved = cand
                break
        if resolved:
            return {"version": version, "targets": {".": path_to_file_url(resolved)}}
        if main is None and any(k in manifest for k in ("bin", "types", "typings")):
            return {"version": version, "targets": {}}
        raise RuntimeError(f"dsh: installed package {package_name} main entry is missing at {entry_path}")

    declared = manifest.get("exports")
    subpaths: List[str] = []
    if isinstance(declared, dict) and any(k.startswith(".") for k in declared.keys()):
        subpaths = [
            k for k in declared.keys()
            if k == "." or (k.startswith("./") and "*" not in k and not k.endswith("/") and k != "./package.json")
        ]
    else:
        subpaths = ["."]

    targets: Dict[str, str] = {}
    for subpath in subpaths:
        target = package_entry_from_package(package_name, package_dir, declared, subpath)
        if target is not None:
            targets[subpath] = target
    return {"version": version, "targets": targets}


def ensure_module_proxy(
    link: str,
    package_name: str,
    version: str,
    targets: Dict[str, str],
) -> None:
    """Materialize a real package proxy retaining pkg virtual module URL."""
    proxy_exports = {subpath: f"./entry-{idx}.js" for idx, subpath in enumerate(targets.keys())}
    manifest = {
        "name": package_name,
        "version": version,
        "private": True,
        "type": "module",
        "exports": proxy_exports,
        "dsh": {"moduleFallback": {"targets": targets}},
    }

    if is_symlink_or_junction(link):
        os.unlink(link)
    elif os.path.exists(link):
        existing = read_module_proxy_record(link)
        if not existing or "dsh" not in existing or "moduleFallback" not in existing.get("dsh", {}) or "targets" not in existing.get("dsh", {}).get("moduleFallback", {}):
            raise RuntimeError(
                f"dsh: {link} exists and is not a dsh-managed module proxy; remove it so dsh can manage the installation fallback"
            )
        if (
            existing.get("version") == version
            and existing.get("dsh", {}).get("moduleFallback", {}).get("targets") == targets
            and all(os.path.exists(os.path.join(link, f"entry-{idx}.js")) for idx in range(len(targets)))
        ):
            return
        shutil.rmtree(link)

    os.makedirs(link, exist_ok=True)
    with open(os.path.join(link, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    for idx, target in enumerate(targets.values()):
        specifier = json.dumps(target)
        with open(os.path.join(link, f"entry-{idx}.js"), "w", encoding="utf-8") as f:
            f.write(f"export * from {specifier}\nimport * as target from {specifier}\nexport default target.default\n")


def read_module_fallback_manifest(anchor: str) -> Dict[str, Any]:
    """Read one package manifest used while traversing fallback graph."""
    with open(anchor, "r", encoding="utf-8") as f:
        return json.load(f)


def profile_dependency_names(manifest: Dict[str, Any]) -> List[str]:
    """Return dependency and peerDependency names."""
    deps = list(manifest.get("dependencies", {}).keys())
    peer_deps = list(manifest.get("peerDependencies", {}).keys())
    return deps + [p for p in peer_deps if p not in deps]


def package_dir_from_anchor(
    anchor: str,
    package_name: str,
    exclude: Optional[Callable[[str, str], bool]] = None,
) -> Optional[str]:
    """Resolve package root by probing parent node_modules directories with portable packages/ layout fallback."""
    curr = os.path.dirname(os.path.abspath(anchor))
    while True:
        candidate = os.path.join(curr, "node_modules", package_name)
        if os.path.exists(os.path.join(candidate, "package.json")):
            if exclude is None or not exclude(candidate, package_name):
                return candidate

        # Portable / workspace packages/ layout fallback
        pkgs_dir = os.path.join(curr, "packages")
        if os.path.isdir(pkgs_dir):
            if package_name.startswith("@deepseek-ai/dsh-"):
                bundle_sub = package_name[len("@deepseek-ai/dsh-"):]
                b_cand = os.path.join(pkgs_dir, "bundle", bundle_sub)
                if os.path.exists(os.path.join(b_cand, "package.json")):
                    if exclude is None or not exclude(b_cand, package_name):
                        return b_cand
            for cat in ("bundle", "boot", "client", "preset", "core", "api", "attachment"):
                cat_dir = os.path.join(pkgs_dir, cat)
                if os.path.isdir(cat_dir):
                    for sub in os.listdir(cat_dir):
                        sub_cand = os.path.join(cat_dir, sub)
                        sub_pkg = os.path.join(sub_cand, "package.json")
                        if os.path.isfile(sub_pkg):
                            try:
                                with open(sub_pkg, "r", encoding="utf-8") as f:
                                    m = json.load(f)
                                if m.get("name") == package_name:
                                    if exclude is None or not exclude(sub_cand, package_name):
                                        return sub_cand
                            except Exception:
                                pass

        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return None


def resolve_module_fallback_entries(
    install_anchor: str,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Resolve installation fallback entries and package names."""
    app_manifest = read_module_fallback_manifest(install_anchor)
    links: Dict[str, str] = {}
    if "name" in app_manifest:
        links[app_manifest["name"]] = os.path.dirname(os.path.abspath(install_anchor))

    queue = [{"anchor": install_anchor, "manifest": app_manifest}]
    while queue:
        item = queue.pop(0)
        for dep in profile_dependency_names(item["manifest"]):
            if dep in links:
                continue
            dir_path = package_dir_from_anchor(item["anchor"], dep)
            if dir_path is None:
                continue
            links[dep] = dir_path
            manifest_path = os.path.join(dir_path, "package.json")
            if os.path.exists(manifest_path):
                queue.append({"anchor": manifest_path, "manifest": read_module_fallback_manifest(manifest_path)})

    if not is_packaged_executable():
        entries = [{"kind": "symlink", "packageName": pkg, "packageDir": pdir} for pkg, pdir in links.items()]
    else:
        entries = []
        for pkg, pdir in links.items():
            source = package_proxy_source(pkg, pdir)
            if source["targets"]:
                entries.append({"kind": "proxy", "packageName": pkg, "version": source["version"], "targets": source["targets"]})
    return entries, set(links.keys())


def module_fallback_entry_current(modules_dir: str, entry: Dict[str, Any]) -> bool:
    """Return whether one fallback entry already matches current generation."""
    link = os.path.join(modules_dir, entry["packageName"])
    try:
        if entry["kind"] == "symlink":
            return is_symlink_or_junction(link) and symlink_points_to(link, entry["packageDir"])
        if not os.path.isdir(link) or is_symlink_or_junction(link):
            return False
        existing = read_module_proxy_record(link)
        if not existing:
            return False
        targets = entry["targets"]
        return (
            existing.get("version") == entry["version"]
            and existing.get("dsh", {}).get("moduleFallback", {}).get("targets") == targets
            and all(os.path.exists(os.path.join(link, f"entry-{idx}.js")) for idx in range(len(targets)))
        )
    except Exception:
        return False


def module_fallback_current(modules_dir: str, entries: Sequence[Dict[str, Any]]) -> bool:
    """Return whether every required fallback entry is current."""
    return all(module_fallback_entry_current(modules_dir, entry) for entry in entries)


def dependency_closure(
    anchors: Sequence[str],
    reserved: Set[str],
    exclude: Callable[[str, str], bool],
) -> Dict[str, str]:
    """Collect first resolvable package directory for each dependency name."""
    links: Dict[str, str] = {}
    visited = set(reserved)
    for anchor in anchors:
        if not os.path.exists(anchor):
            continue
        canonical_anchor = os.path.realpath(anchor)
        manifest = read_module_fallback_manifest(canonical_anchor)
        if "name" in manifest:
            name = manifest["name"]
            if name not in visited:
                visited.add(name)
                links[name] = os.path.dirname(canonical_anchor)
        queue = [{"anchor": canonical_anchor, "manifest": manifest}]
        while queue:
            item = queue.pop(0)
            for dep in profile_dependency_names(item["manifest"]):
                if dep in visited:
                    continue
                d = package_dir_from_anchor(item["anchor"], dep, exclude=exclude)
                if d is None:
                    continue
                visited.add(dep)
                links[dep] = d
                manifest_path = os.path.join(d, "package.json")
                if os.path.exists(manifest_path):
                    queue.append({"anchor": manifest_path, "manifest": read_module_fallback_manifest(manifest_path)})
    return links


def heal_profile_module_fallback(profile: Any, installation_package_names: Set[str]) -> None:
    """Reconcile packages carried only by selected bundles into profile directory."""
    profile_dir = profile.dir if hasattr(profile, "dir") else profile["dir"]
    layers = profile.layers if hasattr(profile, "layers") else profile["layers"]
    profile_modules_dir = os.path.join(profile_dir, "node_modules")
    owned_modules_dir = os.path.join(profile_dir, PROFILE_MODULE_FALLBACK_DIR, "node_modules")
    os.makedirs(profile_modules_dir, exist_ok=True)
    os.makedirs(owned_modules_dir, exist_ok=True)

    bundle_anchors = []
    for layer in layers:
        pkg_name = layer.packageName if hasattr(layer, "packageName") else layer["packageName"]
        pkg_dir = layer.packageDir if hasattr(layer, "packageDir") else layer["packageDir"]
        if pkg_name not in installation_package_names:
            bundle_anchors.append(os.path.join(pkg_dir, "package.json"))

    def _exclude(candidate: str, package_name: str) -> bool:
        profile_link = os.path.join(profile_modules_dir, package_name)
        if canonical_link_path(candidate) != canonical_link_path(profile_link):
            return False
        try:
            return is_symlink_or_junction(profile_link) and symlink_points_to(profile_link, os.path.join(owned_modules_dir, package_name))
        except Exception:
            return False

    bundle_links = dependency_closure(bundle_anchors, installation_package_names, _exclude)
    for layer in layers:
        pkg_name = layer.packageName if hasattr(layer, "packageName") else layer["packageName"]
        bundle_links.pop(pkg_name, None)

    for package_name in owned_package_names(owned_modules_dir):
        if package_name not in bundle_links:
            remove_profile_symlink(profile_modules_dir, owned_modules_dir, package_name)

    for package_name, target in bundle_links.items():
        owned_link = os.path.join(owned_modules_dir, package_name)
        os.makedirs(os.path.dirname(owned_link), exist_ok=True)
        ensure_symlink(owned_link, target)
        profile_link = os.path.join(profile_modules_dir, package_name)
        os.makedirs(os.path.dirname(profile_link), exist_ok=True)
        ensure_profile_symlink(profile_link, owned_link)


def heal_profiles_module_fallback_locked(
    entries: Sequence[Dict[str, Any]],
    modules_dir: str,
) -> None:
    """Heal fallback links/proxies while file lock is held."""
    for entry in entries:
        link = os.path.join(modules_dir, entry["packageName"])
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if entry["kind"] == "proxy":
            ensure_module_proxy(link, entry["packageName"], entry["version"], entry["targets"])
        else:
            ensure_symlink(link, entry["packageDir"])


async def heal_profiles_module_fallback(options: Dict[str, Any]) -> None:
    """Maintain module fallbacks for one profile launch matching TS healProfilesModuleFallback."""
    install_anchor = options.get("installAnchor", "")
    profile = options.get("profile")
    home = options.get("home") or resolve_dsh_home()
    profiles_dir = os.path.join(home, PROFILES_DIR)
    modules_dir = os.path.join(profiles_dir, "node_modules")
    os.makedirs(modules_dir, exist_ok=True)

    entries, package_names = resolve_module_fallback_entries(install_anchor)
    if not module_fallback_current(modules_dir, entries):
        async def _locked():
            if not module_fallback_current(modules_dir, entries):
                heal_profiles_module_fallback_locked(entries, modules_dir)

        await with_file_lock(modules_dir, _locked)

    if profile is not None:
        heal_profile_module_fallback(profile, package_names)


def resolve_profile_dir(name: str, home: Optional[str] = None) -> str:
    """Resolve a profile's directory under the Harness home."""
    if (
        not name
        or "/" in name
        or "\\" in name
        or name == "."
        or name == ".."
        or name == "node_modules"
    ):
        raise ValueError(f"dsh: invalid profile name {json.dumps(name)}")
    base_home = home or resolve_dsh_home()
    return os.path.join(base_home, PROFILES_DIR, name)


def init_profile(
    dir_path: str,
    bundles: Sequence[str],
    patch_reload: str = DEFAULT_PROFILE_PATCH_RELOAD,
) -> None:
    """Initialize a profile directory: manifest, empty user patch layer, pnpm workspace."""
    os.makedirs(dir_path, exist_ok=True)
    manifest_path = os.path.join(dir_path, "package.json")
    if not os.path.exists(manifest_path):
        manifest = {
            "name": f"dsh-profile-{os.path.basename(dir_path)}",
            "private": True,
            "dependencies": {},
            "dsh": {"profile": {"bundles": list(bundles), "patchReload": patch_reload}},
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

    patch_path = os.path.join(dir_path, PROFILE_PATCH_FILENAME)
    if not os.path.exists(patch_path):
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(PROFILE_PATCH_TEMPLATE)

    workspace_path = os.path.join(dir_path, "pnpm-workspace.yaml")
    if not os.path.exists(workspace_path):
        with open(workspace_path, "w", encoding="utf-8") as f:
            f.write(PROFILE_PNPM_WORKSPACE)


def read_profile_manifest(bin_name: str, dir_path: str) -> Dict[str, Any]:
    """Read a profile manifest."""
    manifest_path = os.path.join(dir_path, "package.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to read profile manifest {manifest_path}: {e}")

    try:
        parsed = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to read profile manifest {manifest_path}: {e}")

    if not isinstance(parsed, dict) or isinstance(parsed, list):
        raise RuntimeError(f"{bin_name}: profile manifest {manifest_path} must hold a JSON object")
    return parsed


def write_profile_manifest(dir_path: str, manifest: Dict[str, Any]) -> None:
    """Write a profile manifest."""
    manifest_path = os.path.join(dir_path, "package.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def normalize_shipped_profile(
    name: str,
    dir_path: str,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize installation-owned bundle tuple to shipped template."""
    installation_owned = INSTALLATION_OWNED_PROFILE_TUPLES.get(name)
    template = PROFILE_TEMPLATES.get(name)
    bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles")
    if template is None or bundles is None:
        return manifest

    is_retired = installation_owned is not None and bundles == installation_owned
    is_current = bundles == template["bundles"]
    needs_reload = manifest.get("dsh", {}).get("profile", {}).get("patchReload") is None and is_current

    if not is_retired and not needs_reload:
        return manifest

    normalized = copy.deepcopy(manifest)
    normalized.setdefault("dsh", {}).setdefault("profile", {})["bundles"] = list(template["bundles"])
    normalized["dsh"]["profile"]["patchReload"] = (
        manifest.get("dsh", {}).get("profile", {}).get("patchReload") or template["patchReload"]
    )
    write_profile_manifest(dir_path, normalized)
    return normalized


def resolve_bundle_dir(
    bin_name: str,
    package_name: str,
    install_anchor: str,
    profile_dir: str,
) -> str:
    """Resolve bundle directory: install_anchor first, then profile_dir."""
    anchors = [install_anchor, os.path.join(profile_dir, "package.json")]
    for anchor in anchors:
        d = package_dir_from_anchor(anchor, package_name)
        if d is not None:
            return d

    raise RuntimeError(
        f"{bin_name}: cannot resolve profile bundle {json.dumps(package_name)} from the dsh installation or {profile_dir}; "
        f"run 'dsh plugin --profile {os.path.basename(profile_dir)} install' if its dependency is not installed"
    )


def load_profile(
    bin_name: str,
    name: str,
    install_anchor: str,
    home: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Profile:
    """Load a profile: resolve bundle layers and parse user patch layer."""
    from dsh.boot.app_boot import load_overlay_patches
    opts = options or {}
    base_home = home or resolve_dsh_home()
    profile_dir = resolve_profile_dir(name, base_home)
    manifest_path = os.path.join(profile_dir, "package.json")

    if not os.path.exists(manifest_path):
        template = PROFILE_TEMPLATES.get(name)
        if template is None:
            raise RuntimeError(
                f"{bin_name}: profile {json.dumps(name)} does not exist; create it with 'dsh plugin --profile {name} add <package>'"
            )
        init_profile(profile_dir, template["bundles"], template["patchReload"])

    manifest = normalize_shipped_profile(name, profile_dir, read_profile_manifest(bin_name, profile_dir))
    bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles", [])
    raw_reload = manifest.get("dsh", {}).get("profile", {}).get("patchReload")
    if raw_reload is not None and raw_reload not in ("live", "startup"):
        raise RuntimeError(
            f"{bin_name}: profile manifest {manifest_path} dsh.profile.patchReload must be \"live\" or \"startup\""
        )
    patch_reload = raw_reload or DEFAULT_PROFILE_PATCH_RELOAD

    layers: List[ProfileLayer] = []
    for b_name in bundles:
        b_dir = resolve_bundle_dir(bin_name, b_name, install_anchor, profile_dir)
        with open(os.path.join(b_dir, "package.json"), "r", encoding="utf-8") as f:
            b_manifest = json.load(f)
        patch_rel = b_manifest.get("dsh", {}).get("bundle", {}).get("patch")
        if patch_rel is None:
            raise RuntimeError(f"{bin_name}: profile bundle {json.dumps(b_name)} declares no dsh.bundle in its package.json")
        b_patch_path = os.path.normpath(os.path.join(b_dir, patch_rel))
        b_patches = load_overlay_patches(bin_name, b_patch_path)
        layers.append(ProfileLayer(b_name, b_dir, b_patch_path, b_patches))

    user_patch_path = os.path.join(profile_dir, PROFILE_PATCH_FILENAME)
    user_patches: List[Dict[str, Any]] = []
    if opts.get("userLayer") is not False and os.path.exists(user_patch_path):
        user_patches = load_overlay_patches(bin_name, user_patch_path)

    return Profile(
        name=name,
        dir_path=profile_dir,
        layers=layers,
        patch_path=user_patch_path,
        patches=user_patches,
        patch_reload=patch_reload,
    )


def compose_entries(
    layers: Sequence[Sequence[Dict[str, Any]]],
    warn: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """Compose patch layers over an empty root entry list matching TS composeEntries."""
    flattened = [copy.deepcopy(p) for layer in layers for p in layer]

    def _warn_handler(msg: str, *args: Any):
        if warn is not None:
            formatted = msg
            if args:
                idx = 0
                def _rep(m):
                    nonlocal idx
                    if idx < len(args):
                        res = json.dumps(args[idx])
                        idx += 1
                        return res
                    return m.group(0)
                formatted = re.sub(r"%C", _rep, msg)
                if idx < len(args):
                    try:
                        formatted = formatted % args[idx:]
                    except Exception:
                        pass
            warn(formatted)

    return apply_entry_patches([], flattened, warn=_warn_handler)


# CamelCase aliases for TS parity
resolveProfileDir = resolve_profile_dir
initProfile = init_profile
readProfileManifest = read_profile_manifest
writeProfileManifest = write_profile_manifest
resolveBundleDir = resolve_bundle_dir
loadProfile = load_profile
composeEntries = compose_entries
healProfilesModuleFallback = heal_profiles_module_fallback
healProfileModuleFallback = heal_profile_module_fallback
ensureSymlink = ensure_symlink
ensureProfileSymlink = ensure_profile_symlink
removeProfileSymlink = remove_profile_symlink
isPackagedExecutable = is_packaged_executable
normalizeShippedProfile = normalize_shipped_profile
packageDirFromAnchor = package_dir_from_anchor
