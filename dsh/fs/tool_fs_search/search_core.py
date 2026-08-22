import os
from typing import Any, Dict, List, Optional, Tuple


EXCLUDED_DIRS = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl", "__pycache__", ".venv", "node_modules"}


def strip_leading_separators(path: str) -> str:
    start = 0
    while start < len(path) and path[start] in ("/", "\\"):
        start += 1
    return path[start:]


def top_level_segment(path: str) -> str:
    trimmed = strip_leading_separators(path)
    cut_fwd = trimmed.find("/")
    cut_back = trimmed.find("\\")
    cut = min([c for c in [cut_fwd, cut_back] if c != -1], default=-1)
    return trimmed[:cut] if cut != -1 else trimmed


def relative_to_search_root(path: str, root: str) -> str:
    if root in (".", "./", ".\\"):
        return path[2:] if path.startswith(("./", ".\\")) else path
    trimmed_root = root.rstrip("/\\")
    if not trimmed_root:
        return strip_leading_separators(path)
    if path == trimmed_root:
        return ""
    if path.startswith(trimmed_root + "/") or path.startswith(trimmed_root + "\\"):
        return path[len(trimmed_root) + 1 :]
    return path
