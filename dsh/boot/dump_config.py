"""
Config-dump entry for `dsh --profile <name> --dump-config`.
Matching reference/apps/cli/src/dump-config.ts 1:1.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import sys
from typing import List, Sequence

from dsh.boot.app_boot import (
    load_optional_patches,
    load_overlay_patches,
    render_config_dump,
)
from dsh.boot.profile_boot import (
    home_patch_path,
    prepare_profile,
    PROFILE_ROOT_FILENAME,
    NAME,
)


def run_dump_config(profile: str, default_only: bool, patches: Sequence[str] = ()) -> str:
    """
    Print a profile composition with comments naming each source file and patch layer.
    """
    loaded = prepare_profile(profile, not default_only)
    layers = [
        {"label": layer.packageName, "patches": layer.patches}
        for layer in loaded.layers
    ]
    if not default_only:
        if os.path.exists(loaded.patchPath):
            layers.append({"label": loaded.patchPath, "patches": loaded.patches})
        home_patch_file = home_patch_path()
        home_patches = load_optional_patches(NAME, home_patch_file)
        if home_patches is not None:
            layers.append({"label": home_patch_file, "patches": home_patches})
        for file in patches:
            absolute = os.path.abspath(file)
            layers.append({"label": absolute, "patches": load_overlay_patches(NAME, absolute)})

    root_config_path = os.path.join(loaded.dir, PROFILE_ROOT_FILENAME)
    dump_text = render_config_dump(NAME, root_config_path, layers)
    return dump_text


runDumpConfig = run_dump_config
