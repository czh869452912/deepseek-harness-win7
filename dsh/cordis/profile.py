"""
Cordis Profile & Multi-layer Bundle Cascading System
Matching reference/apps/cli/src/profile-boot.ts and @deepseek-ai/dsh-app-boot.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
from typing import Any, Callable, Dict, List, Optional
import yaml

from dsh.cordis.loader import js_constructor  # Register the upstream !!js YAML tag.
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
    """Construct the canonical profile lazily, avoiding package bootstrap cycles."""
    def __new__(cls, *args, **kwargs):
        from dsh.boot.profile import Profile as CanonicalProfile
        return CanonicalProfile(*args, **kwargs)


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
    creative_patches = _read_bundle_patch("creative")

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
        "dsh-creative": creative_patches,
        "@deepseek-win7/dsh-creative": creative_patches,
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
    # Native creative alias adds its tools as a separately owned bundle.
    "creative": {
        "bundles": ["dsh-base", "dsh-headless", "dsh-creative"],
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
    """Delegate discovery, initialization and root writing to canonical boot."""
    from dsh.boot.profile_boot import prepare_profile as prepare
    profile = prepare(name, user_layer=user_layer, dsh_home=dsh_home)
    profile.dir_path = profile.dir
    profile.bundles = [layer.packageName for layer in profile.layers]
    return profile


class ComposedProfile:
    """Construct the canonical layer container after package initialization."""
    def __new__(cls, *args, **kwargs):
        from dsh.boot.profile_boot import ComposedProfile as CanonicalComposed
        return CanonicalComposed(*args, **kwargs)


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
    """Use canonical profile loading and the shared offline layer composer."""
    from dsh.boot.profile_boot import compose_profile_layers
    return compose_profile_layers(prepare_profile(name, dsh_home=dsh_home), patch_files or [], dsh_home)


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
    return run_dump_config(profile_name, default_only=default_only, patches=patch_files or [], dsh_home=dsh_home)


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


