import fnmatch
import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.fs.tool_fs_search.search_core import EXCLUDED_DIRS, relative_to_search_root, top_level_segment


def sample_across_top_level(paths: List[str], max_items: int, root: str = ".") -> Dict[str, Any]:
    groups: Dict[str, List[str]] = {}
    active: List[Dict[str, Any]] = []

    for p in paths:
        rel = relative_to_search_root(p, root)
        key = top_level_segment(rel)
        if key not in groups:
            groups[key] = [p]
            active.append({"key": key, "items": groups[key], "index": 0, "current": p})
        else:
            groups[key].append(p)

    taken: Dict[str, List[str]] = {}
    count = 0

    while active and count < max_items:
        next_active = []
        for entry in active:
            if count >= max_items:
                break
            key = entry["key"]
            current = entry["current"]
            count += 1
            if key not in taken:
                taken[key] = [current]
            else:
                taken[key].append(current)

            next_index = entry["index"] + 1
            items = entry["items"]
            if next_index < len(items):
                next_active.append({
                    "key": key,
                    "items": items,
                    "index": next_index,
                    "current": items[next_index],
                })
        active = next_active

    flat_items: List[str] = []
    for bucket in taken.values():
        flat_items.extend(bucket)

    return {
        "items": flat_items,
        "shown": len(taken),
        "total": len(groups),
    }
