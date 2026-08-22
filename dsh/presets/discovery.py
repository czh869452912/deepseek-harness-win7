"""
Filesystem discovery of agent presets.
1:1 with reference @deepseek-ai/dsh-agent-presets/discovery.ts.
Python 3.8.10 compatible.
"""

import os
from typing import Any, Dict, List, Optional
import yaml

from dsh.presets.metadata import read_preset_metadata
from dsh.presets.preset import PRESET_ID, AgentPreset, PresetRoot


COMPOSITION_FILE = "agent.cordis.yml"
USER_PRESET_DIR = ".agent-presets"


def _expand_home_path(path: str) -> str:
    if path.startswith("~"):
        return os.path.expanduser(path)
    if "$DSH_HOME" in path or "%DSH_HOME%" in path:
        dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
        path = path.replace("$DSH_HOME", dsh_home).replace("%DSH_HOME%", dsh_home)
    return os.path.abspath(path)


def entry_list_problem(rows: Any, at: str = "") -> Optional[str]:
    """
    Why rows cannot be an entry list, or None when it can.
    Validates top-level list of plugin rows.
    """
    if not isinstance(rows, list):
        return (
            "the composition must be a top-level list of plugin rows"
            if at == ""
            else f"group {at} must hold a list of plugin rows"
        )

    for index, row in enumerate(rows):
        label = f"row {index + 1}" if at == "" else f"{at} row {index + 1}"
        if not isinstance(row, dict):
            return f'{label} is not a plugin row (expected a map with a "name")'

        name = row.get("name")
        group = row.get("group")
        config = row.get("config")

        if not isinstance(name, str) or not name:
            return f'{label} names no plugin (a "name" string is required)'

        if group is True:
            nested_prob = entry_list_problem(config, label)
            if nested_prob is not None:
                return nested_prob

    return None


def composition_problem(path: str) -> Optional[str]:
    """
    Why the composition at path cannot mount, or None when loadable.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return f"the composition file {COMPOSITION_FILE} cannot be read"

    try:
        # Ignore !!js tags in YAML parse
        loader = yaml.SafeLoader
        try:
            loader.add_constructor("tag:yaml.org,2002:js", lambda l, n: l.construct_scalar(n))
            loader.add_constructor("!!js", lambda l, n: l.construct_scalar(n))
        except Exception:
            pass
        rows = yaml.load(content, Loader=loader)
    except Exception as e:
        first_line = str(e).split("\n")[0]
        return f"the composition is not valid YAML: {first_line}"

    return entry_list_problem(rows)


def scan_root(root: PresetRoot) -> List[AgentPreset]:
    """
    Scan one root for preset directories (or flat yaml presets).
    Returns discovered presets sorted by order, then by id.
    """
    dir_path = _expand_home_path(root.path)
    if not os.path.exists(dir_path):
        return []

    if not os.path.isdir(dir_path):
        return []

    try:
        entries = os.listdir(dir_path)
    except Exception as e:
        raise RuntimeError(f"agent-presets: cannot read preset root {dir_path}: {e}") from e

    found: List[AgentPreset] = []
    processed_ids = set()

    for entry_name in sorted(entries):
        full_entry = os.path.join(dir_path, entry_name)

        # 1. Directory-based preset (official TS structure)
        if os.path.isdir(full_entry) and PRESET_ID.match(entry_name):
            pid = entry_name
            processed_ids.add(pid)

            # Check composition candidates: agent.cordis.yml, cordis.yml, preset.yaml, f"{pid}.yaml"
            comp_path = os.path.join(full_entry, COMPOSITION_FILE)
            if not os.path.isfile(comp_path):
                alt = os.path.join(full_entry, "cordis.yml")
                if os.path.isfile(alt):
                    comp_path = alt
                else:
                    alt_yaml = os.path.join(full_entry, f"{pid}.yaml")
                    if os.path.isfile(alt_yaml):
                        comp_path = alt_yaml

            if os.path.isfile(comp_path):
                broken = composition_problem(comp_path)
            else:
                broken = f"the composition file {COMPOSITION_FILE} is missing — the directory still occupies the id; delete it or restore the file"

            metadata = read_preset_metadata(full_entry)
            found.append(
                AgentPreset(
                    id=pid,
                    trust=root.trust,
                    path=comp_path,
                    name=metadata.get("name"),
                    description=metadata.get("description"),
                    order=metadata.get("order"),
                    broken=broken,
                )
            )

        # 2. Flat file preset (e.g. minimal.yaml in root dir) for backward compat
        elif os.path.isfile(full_entry) and entry_name.endswith(".yaml"):
            pid = entry_name[:-5]
            if pid not in processed_ids and PRESET_ID.match(pid):
                processed_ids.add(pid)
                broken = composition_problem(full_entry)
                found.append(
                    AgentPreset(
                        id=pid,
                        trust=root.trust,
                        path=full_entry,
                        name=None,
                        description=None,
                        order=None,
                        broken=broken,
                    )
                )

    def sort_key(preset: AgentPreset) -> tuple:
        ord_val = preset.order if preset.order is not None else float("inf")
        return (ord_val, preset.id)

    found.sort(key=sort_key)
    return found


def discover_presets(roots: List[PresetRoot]) -> List[AgentPreset]:
    """
    Scan every root in precedence order. First root wins per preset id.
    """
    by_id: Dict[str, AgentPreset] = {}
    for root in roots:
        for preset in scan_root(root):
            if preset.id not in by_id:
                by_id[preset.id] = preset

    return list(by_id.values())
