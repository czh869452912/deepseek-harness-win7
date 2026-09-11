"""
Cordis Profile & Multi-layer Bundle Cascading System
Matching reference/apps/cli/src/profile-boot.ts and @deepseek-ai/dsh-app-boot.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import apply_entry_patches, sort_keys, js_constructor
from dsh.cordis.environment import resolve_dsh_home


PROFILE_ROOT_FILENAME = "cordis.yml"
PROFILE_PATCH_FILENAME = "cordis.patch.yml"
TELEMETRY_ROW_ID = "session-telemetry-otel"


def home_patch_path(dsh_home: Optional[str] = None) -> str:
    """Return the absolute path of the global user patch ($DSH_HOME/cordis.patch.yml)."""
    home = dsh_home or resolve_dsh_home()
    return os.path.join(home, PROFILE_PATCH_FILENAME)



def load_optional_patches(bin_or_path: str, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load a list of patches from a YAML file if it exists, otherwise return [].
    Delegates to canonical implementation in dsh.boot.app_boot.load_optional_patches.
    """
    if filepath is None:
        bin_name = "dsh"
        target_path = bin_or_path
    else:
        bin_name = bin_or_path
        target_path = filepath
    from dsh.boot.app_boot import load_optional_patches as _boot_load_optional
    res = _boot_load_optional(bin_name, target_path)
    return res if res is not None else []


def load_overlay_patches(bin_or_path: str, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load overlay patches specified by CLI --patch argument.
    Delegates to canonical implementation in dsh.boot.app_boot.load_overlay_patches.
    """
    if filepath is None:
        bin_name = "dsh"
        target_path = bin_or_path
    else:
        bin_name = bin_or_path
        target_path = filepath
    from dsh.boot.app_boot import load_overlay_patches as _boot_load_overlay
    return _boot_load_overlay(bin_name, target_path)


class Profile:
    """Represents a loaded profile definition."""
    def __init__(
        self,
        name: str,
        dir_path: str,
        patch_path: str,
        patches: List[Dict[str, Any]],
        bundles: List[str],
        layers: Optional[List[Any]] = None,
        patch_reload: str = "live",
    ):
        self.name = name
        self.dir = dir_path
        self.dir_path = dir_path
        self.patch_path = patch_path
        self.patchPath = patch_path
        self.patches = patches
        self.bundles = bundles
        self.layers = layers or []
        self.patch_reload = patch_reload
        self.patchReload = patch_reload

    def __repr__(self) -> str:
        return f"<Profile {self.name} dir={self.dir} patches={len(self.patches)} bundles={self.bundles}>"


def _load_builtin_bundles() -> Dict[str, List[Dict[str, Any]]]:
    """Load built-in bundle patches directly from packages/bundle/*/cordis.patch.yml."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    bundle_dir = os.path.join(repo_root, "packages", "bundle")

    def _read_bundle_patch(subdir: str) -> List[Dict[str, Any]]:
        candidate_dirs = [
            os.path.join(repo_root, "packages", "bundle"),
            os.path.join(repo_root, "reference", "packages", "bundle"),
        ]
        for b_dir in candidate_dirs:
            path = os.path.join(b_dir, subdir, "cordis.patch.yml")
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                parsed = yaml.safe_load(content)
                if not isinstance(parsed, list):
                    raise RuntimeError(f"dsh: overlay {path} must be a top-level YAML array of loader patch entries")
                for index, entry in enumerate(parsed):
                    if not isinstance(entry, dict):
                        raise RuntimeError(f"dsh: overlay entry {index + 1} in {path} must be a mapping")
                return parsed
        raise RuntimeError(f"dsh: failed to read bundle patch for '{subdir}': file not found")

    base_patches = _read_bundle_patch("base")
    web_patches = _read_bundle_patch("web-app")
    headless_patches = _read_bundle_patch("headless")
    sdk_patches = _read_bundle_patch("sdk-app")
    acp_patches = _read_bundle_patch("acp-app")
    sdk_min_patches = _read_bundle_patch("sdk-minimal")

    bundles: Dict[str, List[Dict[str, Any]]] = {
        "dsh-base": base_patches,
        "@deepseek-ai/dsh-base": base_patches,
        "dsh-web-app": web_patches,
        "@deepseek-ai/dsh-web-app": web_patches,
        "dsh-headless": headless_patches,
        "@deepseek-ai/dsh-headless": headless_patches,
        "dsh-sdk-app": sdk_patches,
        "@deepseek-ai/dsh-sdk-app": sdk_patches,
        "dsh-acp-app": acp_patches,
        "@deepseek-ai/dsh-acp-app": acp_patches,
        "dsh-sdk-minimal": sdk_min_patches,
        "@deepseek-ai/dsh-sdk-minimal": sdk_min_patches,
    }
    return bundles


# Built-in bundle definitions loaded from packages/bundle/*
BUILTIN_BUNDLES: Dict[str, List[Dict[str, Any]]] = _load_builtin_bundles()

# Built-in profile configurations mapping to bundle lists
BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "web": {
        "bundles": ["dsh-base", "dsh-web-app"],
        "patches": [],
    },
    "headless": {
        "bundles": ["dsh-base", "dsh-headless"],
        "patches": [],
    },
    "standard": {
        "bundles": ["dsh-base", "dsh-headless"],
        "patches": [],
    },
    "minimal": {
        "bundles": ["dsh-sdk-minimal"],
        "patches": [],
    },
    # Creative Mode aligns with the upstream profile shape (bundles only):
    # the host composition carries no invention layer, and @deepseek-ai/dsh-cordis-manager
    # is mounted solely from the agent preset layer (dsh/presets/creative.yaml),
    # matching the upstream separation of host profile vs. agent preset.
    "creative": {
        "bundles": ["dsh-base", "dsh-headless"],
        "patches": [],
    },

    "sdk": {
        "bundles": ["dsh-base", "dsh-sdk-app"],
        "patches": [],
    },
    "sdk-minimal": {
        "bundles": ["dsh-sdk-minimal"],
        "patches": [],
    },
    "acp": {
        "bundles": ["dsh-base", "dsh-acp-app"],
        "patches": [],
    },
}


def prepare_profile(name: str, dsh_home: Optional[str] = None, user_layer: bool = True) -> Profile:
    """
    Load a resolved profile for `name` from $DSH_HOME/profiles/<name> or built-ins.
    Rewrites empty root config on every preparation matching TS profile-boot.ts:118-122.
    """
    if not name or "/" in name or "\\" in name or name in (".", "..", "node_modules"):
        raise ValueError(f"dsh: invalid profile name {name!r}")

    home = dsh_home or resolve_dsh_home()
    profile_dir = os.path.join(home, "profiles", name)
    patch_file = os.path.join(profile_dir, PROFILE_PATCH_FILENAME)

    user_patches = load_optional_patches(patch_file) if user_layer else []

    if name not in BUILTIN_PROFILES and not os.path.isdir(profile_dir):
        raise ValueError(f"dsh: profile {name!r} does not exist; create it with 'dsh plugin --profile {name} add <package>'")

    # Rewrite empty root config on every prepare matching TS profile-boot.ts:118-122 (D8)
    os.makedirs(profile_dir, exist_ok=True)
    root_path = os.path.join(profile_dir, PROFILE_ROOT_FILENAME)
    try:
        with open(root_path, "w", encoding="utf-8") as f:
            f.write("[]\n")
    except Exception:
        pass

    # Synchronize custom BUILTIN_PROFILES entry to PROFILE_TEMPLATES if needed
    from dsh.boot.profile import PROFILE_TEMPLATES
    if name in BUILTIN_PROFILES and name not in PROFILE_TEMPLATES:
        PROFILE_TEMPLATES[name] = {
            "bundles": list(BUILTIN_PROFILES[name].get("bundles", [])),
            "patchReload": BUILTIN_PROFILES[name].get("patchReload", "live" if name == "web" else "startup"),
        }

    # Check for custom profile package.json manifest (D6)
    manifest_path = os.path.join(profile_dir, "package.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            custom_bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles")
            raw_reload = manifest.get("dsh", {}).get("profile", {}).get("patchReload")
            if raw_reload is not None and raw_reload not in ("live", "startup"):
                raise RuntimeError(
                    f"dsh: profile manifest {manifest_path} dsh.profile.patchReload must be \"live\" or \"startup\""
                )
            if custom_bundles is not None:
                return Profile(
                    name=name,
                    dir_path=profile_dir,
                    patch_path=patch_file,
                    patches=user_patches,
                    bundles=list(custom_bundles),
                    patch_reload=raw_reload or "startup",
                )
        except (ValueError, json.JSONDecodeError):
            pass

    if name in BUILTIN_PROFILES:
        meta = BUILTIN_PROFILES[name]
        bundles = list(meta.get("bundles", ["dsh-base"]))
        builtin_patches = list(meta.get("patches", []))
        combined_patches = copy.deepcopy(builtin_patches)
        if user_patches:
            combined_patches.extend(user_patches)
        patch_reload = meta.get("patchReload", "live" if name == "web" else "startup")
        return Profile(
            name=name,
            dir_path=profile_dir,
            patch_path=patch_file,
            patches=combined_patches,
            bundles=bundles,
            patch_reload=patch_reload,
        )

    # Check for custom profile directory with default bundle fallback
    if os.path.isdir(profile_dir):
        return Profile(
            name=name,
            dir_path=profile_dir,
            patch_path=patch_file,
            patches=user_patches,
            bundles=["dsh-base"],
            patch_reload="startup",
        )

    raise ValueError(f"dsh: profile {name!r} does not exist; create it with 'dsh plugin --profile {name} add <package>'")


class ComposedProfile:
    """Container for the 4-layer patch stack."""
    def __init__(
        self,
        profile: Profile,
        bundle_patches: List[Dict[str, Any]],
        home_patches: List[Dict[str, Any]],
        overlays: List[Dict[str, Any]],
    ):
        self.profile = profile
        self.bundle_patches = bundle_patches
        self.bundlePatches = bundle_patches
        self.home_patches = home_patches
        self.homePatches = home_patches
        self.overlays = overlays

    def all_patches(self) -> List[Dict[str, Any]]:
        """Return the complete 4-layer patch list in resolution order."""
        return [
            *self.bundle_patches,
            *self.profile.patches,
            *self.home_patches,
            *self.overlays,
        ]

    allPatches = all_patches


def resolve_telemetry_patch(disabled_env: Optional[str], has_row: bool) -> Optional[Dict[str, Any]]:
    """Resolve telemetry disable patch if DSH_TELEMETRY_DISABLED is set."""
    if not disabled_env or not has_row:
        return None
    return {"id": TELEMETRY_ROW_ID, "disabled": True}


def compose_profile(
    name: str,
    patch_files: Optional[List[str]] = None,
    dsh_home: Optional[str] = None,
) -> ComposedProfile:
    """
    Compose the full 4-layer patch stack for the given profile name matching reference/apps/cli/src/profile-boot.ts.
    
    Layers in application order:
    1. Bundle layers (in bundles order)
    2. Profile-specific patches (profiles/<name>/cordis.patch.yml)
    3. User home global patches ($DSH_HOME/cordis.patch.yml)
    4. CLI overlay patch files (--patch in argv order)
    """
    profile = prepare_profile(name, dsh_home=dsh_home)
    
    # Heal module fallback (D9)
    try:
        from dsh.boot.profile import heal_profiles_module_fallback_locked
        from dsh.boot.profile_boot import INSTALL_ANCHOR
        heal_profiles_module_fallback_locked({"installAnchor": INSTALL_ANCHOR, "profile": profile})
    except Exception:
        pass

    # 1. Bundle Patches
    bundle_patches: List[Dict[str, Any]] = []
    if profile.layers:
        for layer in profile.layers:
            bundle_patches.extend(copy.deepcopy(layer.patches))
    else:
        for bname in profile.bundles:
            if bname in BUILTIN_BUNDLES:
                bundle_patches.extend(copy.deepcopy(BUILTIN_BUNDLES[bname]))
            else:
                raise RuntimeError(
                    f"dsh: cannot resolve profile bundle {json.dumps(bname)} from the dsh installation or {profile.dir}; "
                    f"run 'dsh plugin --profile {os.path.basename(profile.dir)} install' if its dependency is not installed"
                )

    # 2. Home Patches ($DSH_HOME/cordis.patch.yml)
    home_patch = home_patch_path(dsh_home)
    home_patches = load_optional_patches(home_patch)

    # 3. CLI Overlay Patches
    overlays: List[Dict[str, Any]] = []
    if patch_files:
        for pf in patch_files:
            overlays.extend(load_overlay_patches(pf))

    # 4. Check Telemetry on composed rows matching TS
    from dsh.boot.profile import compose_entries
    composed_entries = compose_entries([bundle_patches, profile.patches, home_patches, overlays])
    has_telemetry = any(entry.get("id") == TELEMETRY_ROW_ID for entry in composed_entries if isinstance(entry, dict))
    tel_patch = resolve_telemetry_patch(os.environ.get("DSH_TELEMETRY_DISABLED"), has_telemetry)
    if tel_patch:
        overlays.append(tel_patch)

    return ComposedProfile(
        profile=profile,
        bundle_patches=bundle_patches,
        home_patches=home_patches,
        overlays=overlays,
    )


def dump_config(
    profile_name: str = "standard",
    patch_files: Optional[List[str]] = None,
    dsh_home: Optional[str] = None,
    default_only: bool = False,
) -> str:
    """
    Dump the fully composed 4-layer entry tree as YAML matching `dsh --dump-config`.
    Delegates to canonical run_dump_config with provenance comments.
    """
    from dsh.boot.dump_config import run_dump_config
    try:
        return run_dump_config(profile_name, default_only=default_only, patches=patch_files or [], dsh_home=dsh_home)
    except RuntimeError as e:
        if "does not exist" in str(e) and profile_name in BUILTIN_PROFILES:
            composed = compose_profile(profile_name, patch_files=patch_files, dsh_home=dsh_home)
            from dsh.boot.profile import compose_entries
            final_entries = compose_entries([composed.bundle_patches, composed.profile.patches, composed.home_patches, composed.overlays])
            return yaml.safe_dump(final_entries, sort_keys=False, allow_unicode=True)
        raise


def render_config_dump(
    bin_name: str,
    base_config_path: str,
    layers: List[Dict[str, Any]],
    warn_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Render offline configuration composition with layer provenance comments matching TS renderConfigDump.
    Delegates to canonical implementation in dsh.boot.app_boot without duplicate pre-checks.
    """
    from dsh.boot.app_boot import render_config_dump as _boot_render
    return _boot_render(bin_name, base_config_path, layers, warn=warn_fn)


def resolve_lan_trust(bind_host: str, extra: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Single-sample LAN-trust resolution for the /api browser-trust fence matching TS resolveLanTrust.
    Constrained to bind_host == '0.0.0.0' with non-deduplicated output matching TS [...lanAddresses, ...extra].
    """
    import socket
    extra_list = list(extra or [])
    if bind_host == "0.0.0.0":
        lan_addresses: List[str] = []
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if not ip.startswith("127."):
                    lan_addresses.append(ip)
        except Exception:
            pass
    else:
        lan_addresses = []

    return {
        "lan_addresses": lan_addresses,
        "trusted_hosts": list(lan_addresses) + extra_list,
    }


