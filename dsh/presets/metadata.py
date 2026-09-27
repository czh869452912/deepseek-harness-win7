"""
Display metadata for agent presets: name, description, order.
1:1 with reference @deepseek-ai/dsh-agent-presets/metadata.ts.
Python 3.8.10 compatible.
"""

import os
import math
from typing import Any, Dict, Optional
import yaml


METADATA_FILE = "preset.yml"


def _clean_text(val: Any) -> Optional[str]:
    if not isinstance(val, str):
        return None
    trimmed = val.strip()
    return trimmed if trimmed != "" else None


def read_preset_metadata(directory: str) -> Dict[str, Any]:
    """
    Read one preset directory's display metadata.
    Reads preset.yml (or preset.yaml fallback). Returns empty dict on missing or malformed file.
    """
    candidates = [os.path.join(directory, METADATA_FILE)]
    raw_content: Optional[str] = None
    for cand in candidates:
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    raw_content = f.read()
                break
            except Exception:
                pass

    if raw_content is None:
        return {}

    try:
        parsed = yaml.safe_load(raw_content)
    except Exception:
        return {}

    if not isinstance(parsed, dict):
        return {}

    res: Dict[str, Any] = {}
    name = _clean_text(parsed.get("name"))
    if name is not None:
        res["name"] = name

    desc = _clean_text(parsed.get("description"))
    if desc is not None:
        res["description"] = desc

    order_val = parsed.get("order")
    if (isinstance(order_val, (int, float)) and not isinstance(order_val, bool)
            and math.isfinite(order_val)):
        res["order"] = order_val

    return res


def render_preset_metadata(metadata: Dict[str, Any]) -> Optional[str]:
    """
    Render display metadata as YAML file contents.
    Returns None when there is nothing to store.
    """
    name = _clean_text(metadata.get("name"))
    desc = _clean_text(metadata.get("description"))
    order_val = metadata.get("order")
    order = (order_val if isinstance(order_val, (int, float))
             and not isinstance(order_val, bool) and math.isfinite(order_val) else None)

    if name is None and desc is None and order is None:
        return None

    out: Dict[str, Any] = {}
    if name is not None:
        out["name"] = name
    if desc is not None:
        out["description"] = desc
    if order is not None:
        out["order"] = order

    return yaml.dump(out, allow_unicode=True, sort_keys=False)
