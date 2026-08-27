"""
Copying, reading, and deleting locally authored presets.
1:1 with reference @deepseek-ai/dsh-agent-presets/authoring.ts.
Python 3.8.10 compatible.
"""

import os
import shutil
from typing import List, Optional

from dsh.presets.metadata import METADATA_FILE, render_preset_metadata
from dsh.presets.preset import (
    PRESET_ID,
    AgentPreset,
    InvalidPresetIdError,
    PresetExistsError,
    PresetNotWritableError,
    PresetRoot,
)


def _expand_home_path(path: str) -> str:
    if path.startswith("~"):
        return os.path.expanduser(path)
    if "$DSH_HOME" in path or "%DSH_HOME%" in path:
        dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
        path = path.replace("$DSH_HOME", dsh_home).replace("%DSH_HOME%", dsh_home)
    return os.path.abspath(path)


def writable_root(roots: List[PresetRoot]) -> str:
    """
    The root locally authored presets are written to (first 'user' root).
    """
    for root in roots:
        if root.trust == "user":
            return _expand_home_path(root.path)
    raise PresetNotWritableError("", "this deployment configures no user-writable preset root")


def read_composition(preset: AgentPreset) -> str:
    """Read one preset's composition text."""
    with open(preset.path, "r", encoding="utf-8") as f:
        return f.read()


def copy_composition(
    roots: List[PresetRoot],
    source: AgentPreset,
    id_str: str,
    name: Optional[str] = None,
) -> str:
    """
    Create a preset by copying an existing one's whole directory.
    """
    if not PRESET_ID.match(id_str):
        raise InvalidPresetIdError(id_str)

    w_root = writable_root(roots)
    target_dir = os.path.join(w_root, id_str)

    if os.path.exists(target_dir):
        raise PresetExistsError(id_str)

    try:
        os.makedirs(target_dir, exist_ok=True)
        source_dir = os.path.dirname(source.path)

        if os.path.isdir(source_dir) and source_dir != w_root and os.path.basename(source.path).startswith("agent.cordis"):
            # Copy whole directory if source is a preset directory
            for item in os.listdir(source_dir):
                s_item = os.path.join(source_dir, item)
                d_item = os.path.join(target_dir, item)
                if os.path.isdir(s_item):
                    shutil.copytree(s_item, d_item)
                else:
                    shutil.copy2(s_item, d_item)
        else:
            # Copy composition file directly to target_dir/agent.cordis.yml
            target_comp = os.path.join(target_dir, "agent.cordis.yml")
            shutil.copy2(source.path, target_comp)

        meta_dict = {}
        if name is not None:
            meta_dict["name"] = name
        if source.description is not None:
            meta_dict["description"] = source.description

        rendered = render_preset_metadata(meta_dict)
        meta_path = os.path.join(target_dir, METADATA_FILE)

        if rendered is None:
            if os.path.isfile(meta_path):
                os.remove(meta_path)
        else:
            with open(meta_path, "w", encoding="utf-8") as mf:
                mf.write(rendered)

        if os.name != "nt":
            for current, directories, files in os.walk(target_dir):
                os.chmod(current, 0o700)
                for directory in directories:
                    os.chmod(os.path.join(current, directory), 0o700)
                for filename in files:
                    path = os.path.join(current, filename)
                    executable = bool(os.stat(path).st_mode & 0o100)
                    os.chmod(path, 0o700 if executable else 0o600)

    except Exception as e:
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)
        raise e

    return target_dir


def delete_composition(roots: List[PresetRoot], preset: AgentPreset) -> None:
    """
    Delete a locally authored preset.
    """
    if preset.trust != "user":
        raise PresetNotWritableError(preset.id, "it ships with the deployment")

    w_root = writable_root(roots)
    target_dir = os.path.join(w_root, preset.id)

    norm_preset_path = os.path.abspath(preset.path)
    norm_target_dir = os.path.abspath(target_dir)

    try:
        contained = os.path.commonpath([norm_preset_path, norm_target_dir]) == norm_target_dir
    except ValueError:
        contained = False
    if not contained:
        raise PresetNotWritableError(preset.id, "it does not live under the writable preset root")

    if os.path.isdir(norm_target_dir):
        shutil.rmtree(norm_target_dir)
    elif os.path.isfile(norm_preset_path):
        os.remove(norm_preset_path)
