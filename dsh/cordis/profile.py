"""
Cordis Profile & Multi-layer Bundle Cascading System
Matching reference/apps/cli/src/profile-boot.ts and @deepseek-ai/dsh-app-boot.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import apply_entry_patches, sort_keys, js_constructor


PROFILE_ROOT_FILENAME = "cordis.yml"
PROFILE_PATCH_FILENAME = "cordis.patch.yml"
TELEMETRY_ROW_ID = "session-telemetry-otel"


def resolve_dsh_home() -> str:
    """
    Resolve the DeepSeek Harness home directory.
    Respects $DSH_HOME environment variable, fallback to ~/.dsh.
    """
    env_home = os.environ.get("DSH_HOME")
    if env_home and env_home.strip():
        return os.path.abspath(env_home.strip())
    user_home = os.path.expanduser("~")
    return os.path.abspath(os.path.join(user_home, ".dsh"))


def home_patch_path(dsh_home: Optional[str] = None) -> str:
    """Return the absolute path of the global user patch ($DSH_HOME/cordis.patch.yml)."""
    home = dsh_home or resolve_dsh_home()
    return os.path.join(home, PROFILE_PATCH_FILENAME)



def load_optional_patches(filepath: str) -> List[Dict[str, Any]]:
    """
    Load a list of patches from a YAML file if it exists, otherwise return [].
    Handles !!js and standard YAML entries safely.
    """
    if not os.path.isfile(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            if "patches" in data and isinstance(data["patches"], list):
                return data["patches"]
            elif "plugins" in data and isinstance(data["plugins"], list):
                return data["plugins"]
            return [data]
        return []
    except Exception as e:
        sys.stderr.write(f"[Cordis Profile Warning] Failed to parse patch file {filepath}: {e}\n")
        return []


def load_overlay_patches(filepath: str) -> List[Dict[str, Any]]:
    """Load overlay patches specified by CLI --patch argument."""
    abs_path = os.path.abspath(filepath)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Overlay patch file not found: {abs_path}")
    return load_optional_patches(abs_path)


class Profile:
    """Represents a loaded profile definition."""
    def __init__(
        self,
        name: str,
        dir_path: str,
        patch_path: str,
        patches: List[Dict[str, Any]],
        bundles: List[str],
    ):
        self.name = name
        self.dir = dir_path
        self.patch_path = patch_path
        self.patches = patches
        self.bundles = bundles

    def __repr__(self) -> str:
        return f"<Profile {self.name} dir={self.dir} patches={len(self.patches)} bundles={self.bundles}>"


# Built-in bundle definitions matching reference/packages/bundle/*
BUILTIN_BUNDLES: Dict[str, List[Dict[str, Any]]] = {
    "dsh-base": [
        {"id": "tools", "name": "@deepseek-ai/dsh-tools"},
        {"id": "credentials-local", "name": "@deepseek-ai/dsh-credentials-local"},
        {"id": "settings-file", "name": "@deepseek-ai/dsh-settings-file"},
        {"id": "storage", "name": "@deepseek-ai/dsh-storage"},
        {"id": "workspace", "name": "@deepseek-ai/dsh-workspace"},
        {"id": "user-approval", "name": "@deepseek-ai/dsh-user-approval"},
        {"id": "permission-presets", "name": "@deepseek-ai/dsh-permission-presets"},
        {"id": "commands", "name": "@deepseek-ai/dsh-commands"},
        {"id": "token-meter", "name": "@deepseek-ai/dsh-token-meter"},
        {"id": "llm-retry", "name": "@deepseek-ai/dsh-llm-retry"},
        {"id": "agent", "name": "@deepseek-ai/dsh-agent"},
        {"id": "persona", "name": "@deepseek-ai/dsh-persona"},
        {"id": "agent-instructions", "name": "@deepseek-ai/dsh-agent-instructions"},
        {"id": "file-reference-local", "name": "@deepseek-ai/dsh-file-reference-local"},
        {"id": "time-context", "name": "@deepseek-ai/dsh-time-context"},
        {"id": "fs-local", "name": "@deepseek-ai/dsh-fs-local"},
        {"id": "tool-fs", "name": "@deepseek-ai/dsh-tool-fs"},
        {"id": "tool-str-replace-editor", "name": "@deepseek-ai/dsh-tool-str-replace-editor"},
        {"id": "tool-pwsh", "name": "@deepseek-ai/dsh-tool-pwsh"},
        {"id": "tool-pwsh-persistent", "name": "@deepseek-ai/dsh-tool-pwsh-persistent"},
        {"id": "tool-fs-search", "name": "@deepseek-ai/dsh-tool-fs-search"},
        {"id": "tool-ask-user", "name": "@deepseek-ai/dsh-tool-ask-user"},
        {"id": "tool-todo", "name": "@deepseek-ai/dsh-tool-todo"},
        {"id": "skill-filesystem", "name": "@deepseek-ai/dsh-skill-filesystem"},
        {"id": "tool-skill", "name": "@deepseek-ai/dsh-tool-skill"},
        {"id": "session-persistence-jsonl", "name": "@deepseek-ai/dsh-session-persistence-jsonl"},
        {"id": "compaction-tool-result-pruner", "name": "@deepseek-ai/dsh-compaction-tool-result-pruner"},
        {"id": "compaction-basic", "name": "@deepseek-ai/dsh-compaction-basic"},
        {"id": "plan-mode", "name": "@deepseek-ai/dsh-plan-mode"},
        {"id": "tool-goal", "name": "@deepseek-ai/dsh-tool-goal"},
        {"id": "repeat-tool-reminder", "name": "@deepseek-ai/dsh-repeat-tool-reminder"},
        {"id": "tool-call-timeout-policy", "name": "@deepseek-ai/dsh-tool-call-timeout-policy"},
        {"id": "tool-jobs", "name": "@deepseek-ai/dsh-tool-jobs"},
        {"id": "spill-local", "name": "@deepseek-ai/dsh-spill-local"},
        {"id": "tool-subagent", "name": "@deepseek-ai/dsh-tool-subagent"},
        {"id": "tool-workflow", "name": "@deepseek-ai/dsh-tool-workflow"},
    ],
    "dsh-web-app": [
        {"id": "host-webserver", "name": "@deepseek-ai/dsh-host-webserver"},
        {"id": "host-frontend-static", "name": "@deepseek-ai/dsh-host-frontend-static"},
        {"id": "host-client-modules", "name": "@deepseek-ai/dsh-host-client-modules"},
        {"id": "host-directory-picker", "name": "@deepseek-ai/dsh-host-directory-picker"},
        {"id": "host-plugin-inventory", "name": "@deepseek-ai/dsh-host-plugin-inventory"},
        {"id": "host-apiproxy", "name": "@deepseek-ai/dsh-host-apiproxy"},
    ],
    "dsh-headless": [
        {"id": "cli-visualizer", "name": "@deepseek-ai/dsh-cli-visualizer", "config": {"verbose": True}},
    ],
    "dsh-sdk-app": [
        {"id": "session-query-sqlite", "name": "@deepseek-ai/dsh-session-query-sqlite"},
    ],
    "dsh-acp-app": [
        {"id": "acp-server", "name": "@deepseek-ai/dsh-acp-server", "disabled": False},
    ],
    "dsh-sdk-minimal": [
        {"id": "tools", "name": "@deepseek-ai/dsh-tools"},
        {"id": "tool-str-replace-editor", "name": "@deepseek-ai/dsh-tool-str-replace-editor"},
        {"id": "tool-pwsh", "name": "@deepseek-ai/dsh-tool-pwsh"},
        {"id": "agent", "name": "@deepseek-ai/dsh-agent"},
        {"id": "persona", "name": "@deepseek-ai/dsh-persona"},
        {"id": "agent-instructions", "name": "@deepseek-ai/dsh-agent-instructions"},
        {"id": "agent-loop", "name": "@deepseek-ai/dsh-agent-loop"},
    ],
}

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
    "creative": {
        "bundles": ["dsh-base", "dsh-headless"],
        "patches": [
            {"insert": [{"id": "cordis-manager", "name": "@deepseek-ai/dsh-cordis-manager"}]}
        ],
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
    """
    home = dsh_home or resolve_dsh_home()
    profile_dir = os.path.join(home, "profiles", name)
    patch_file = os.path.join(profile_dir, PROFILE_PATCH_FILENAME)

    user_patches = load_optional_patches(patch_file) if user_layer else []

    if name in BUILTIN_PROFILES:
        meta = BUILTIN_PROFILES[name]
        bundles = list(meta.get("bundles", ["dsh-base"]))
        builtin_patches = list(meta.get("patches", []))
        combined_patches = copy.deepcopy(builtin_patches)
        if user_patches:
            combined_patches.extend(user_patches)
        return Profile(
            name=name,
            dir_path=profile_dir,
            patch_path=patch_file,
            patches=combined_patches,
            bundles=bundles,
        )

    # Check for custom profile in $DSH_HOME/profiles/<name>
    if os.path.isdir(profile_dir):
        return Profile(
            name=name,
            dir_path=profile_dir,
            patch_path=patch_file,
            patches=user_patches,
            bundles=["dsh-base"],
        )

    # Fallback to standard
    return prepare_profile("standard", dsh_home=home, user_layer=user_layer)


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
        self.home_patches = home_patches
        self.overlays = overlays

    def all_patches(self) -> List[Dict[str, Any]]:
        """Return the complete 4-layer patch list in resolution order."""
        return [
            *self.bundle_patches,
            *self.profile.patches,
            *self.home_patches,
            *self.overlays,
        ]


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
    
    # 1. Bundle Patches
    bundle_patches: List[Dict[str, Any]] = []
    for bname in profile.bundles:
        if bname in BUILTIN_BUNDLES:
            bundle_patches.extend(copy.deepcopy(BUILTIN_BUNDLES[bname]))

    # 2. Home Patches ($DSH_HOME/cordis.patch.yml)
    home_patch = home_patch_path(dsh_home)
    home_patches = load_optional_patches(home_patch)

    # 3. CLI Overlay Patches
    overlays: List[Dict[str, Any]] = []
    if patch_files:
        for pf in patch_files:
            overlays.extend(load_overlay_patches(pf))

    # 4. Check Telemetry
    all_raw = [*bundle_patches, *profile.patches, *home_patches, *overlays]
    has_telemetry = any(entry.get("id") == TELEMETRY_ROW_ID for entry in all_raw if isinstance(entry, dict))
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
) -> str:
    """
    Dump the fully composed 4-layer entry tree as YAML matching `dsh --dump-config`.
    Pure configuration evaluation without booting the live Context or plugins.
    """
    composed = compose_profile(profile_name, patch_files=patch_files, dsh_home=dsh_home)
    
    # Base bundle entries
    initial_entries = copy.deepcopy(composed.bundle_patches)
    
    # Apply profile, home, and overlay patches
    final_entries = apply_entry_patches(initial_entries, [*composed.profile.patches, *composed.home_patches, *composed.overlays])
    
    sorted_entries = [sort_keys(dict(e)) for e in final_entries]
    return yaml.safe_dump(sorted_entries, sort_keys=False, allow_unicode=True)


def render_config_dump(
    bin_name: str,
    base_config_path: str,
    layers: List[Dict[str, Any]],
    warn_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Render offline configuration composition with layer provenance comments matching TS renderConfigDump.
    layers: list of dicts with 'label' and 'patches'.
    """
    if not os.path.exists(base_config_path):
        raise FileNotFoundError(f"{bin_name}: failed to read config {base_config_path}")

    with open(base_config_path, "r", encoding="utf-8") as f:
        content = f.read()

    base_entries = yaml.safe_load(content) or []
    if not isinstance(base_entries, list):
        raise ValueError(f"{bin_name}: config {base_config_path} must be a top-level YAML array of entries")

    base_label = os.path.basename(base_config_path)
    provenance: List[Dict[str, Any]] = [{"origin": base_label, "patchedBy": []} for _ in base_entries]

    composed = copy.deepcopy(base_entries)
    previous = copy.deepcopy(base_entries)

    for layer in layers:
        label = layer.get("label", "overlay")
        raw_patches = layer.get("patches", [])
        patches = copy.deepcopy(raw_patches)

        # Apply layer patches
        composed = apply_entry_patches(composed, patches)

        # Track provenance
        before_len = len(previous)
        for idx, entry in enumerate(composed):
            if idx >= before_len:
                provenance.append({"origin": label, "patchedBy": []})
            elif idx < len(provenance) and entry != previous[idx]:
                if label not in provenance[idx]["patchedBy"]:
                    provenance[idx]["patchedBy"].append(label)

        previous = copy.deepcopy(composed)

    # Group dump by contiguous provenance
    lines = []
    current_label = None
    group: List[Any] = []

    def flush():
        nonlocal current_label, group
        if current_label and group:
            lines.append(f"# == {current_label}")
            dumped = yaml.safe_dump(group, sort_keys=False, allow_unicode=True).rstrip()
            lines.append(dumped)
            group = []

    for entry, prov in zip(composed, provenance):
        origin = prov["origin"]
        patched = prov["patchedBy"]
        if patched:
            entry_label = f"{origin}, patched by {', '.join(patched)}"
        else:
            entry_label = origin

        if current_label is None or entry_label == current_label:
            current_label = entry_label
            group.append(entry)
        else:
            flush()
            current_label = entry_label
            group.append(entry)

    flush()
    return "\n".join(lines) + "\n"


def resolve_lan_trust(bind_host: str, extra: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Single-sample LAN-trust resolution for the /api browser-trust fence matching TS resolveLanTrust.
    """
    import socket
    extra_list = list(extra or [])
    if bind_host in ("0.0.0.0", "::", ""):
        lan_addresses: List[str] = []
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if not ip.startswith("127.") and ip not in lan_addresses:
                    lan_addresses.append(ip)
        except Exception:
            pass
    else:
        lan_addresses = []

    return {
        "lan_addresses": lan_addresses,
        "trusted_hosts": list(lan_addresses) + extra_list,
    }


