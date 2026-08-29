"""
Path canonicalization for workspace identity.
Aligned 1:1 with official `@deepseek-ai/dsh-workspace/src/paths`.
"""

import os
from typing import Optional


def realpath_normalize(path: str) -> str:
    """
    Canonicalize a directory path via `os.path.realpath`: trailing slashes,
    relative segments, and symlinks are all resolved.
    Raises FileNotFoundError if the path does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No such file or directory: '{path}'")
    canonical = os.path.realpath(path)
    return os.path.normpath(canonical).replace("\\", "/")
def is_windows_style_path(value: str) -> bool:
    """Whether a path uses a Windows drive or UNC prefix."""
    if not value or not isinstance(value, str):
        return False
    if len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in ("/\\"):
        return True
    return value.startswith("\\\\")


def resolve_workspace_path(cwd: Optional[str], path: str) -> str:
    """
    Resolve a Workspace-relative path into the Host-facing spelling used by path operations.
    Matching TS resolveWorkspacePath.
    """
    if not path:
        return path
    if path.startswith("/") or is_windows_style_path(path):
        return path
    if cwd is None or cwd == "":
        return path
    base = cwd.rstrip("/\\")
    relative = path.lstrip("/\\")
    return f"{base}/{relative}"


def abbreviate_home_path(path: str, home: Optional[str] = None) -> str:
    """
    Abbreviate a POSIX home directory for display.
    Matching TS abbreviateHomePath.
    """
    if home is None or home == "":
        return path
    if is_windows_style_path(path) or is_windows_style_path(home):
        return path
    root = home.rstrip("/")
    if root == "" or root == "/":
        return path
    if path.rstrip("/") == root:
        return "~"
    if path.startswith(f"{root}/"):
        return f"~{path[len(root):]}"
    return path


def workspace_title_of(path: str) -> str:
    """
    Read the final non-empty segment of a Workspace path for display.
    Matching TS workspaceTitleOf.
    """
    trimmed = path.rstrip("/\\")
    if not trimmed:
        return ""
    sep = max(trimmed.rfind("/"), trimmed.rfind("\\"))
    return trimmed[sep + 1 :]


realpathNormalize = realpath_normalize
resolveWorkspacePath = resolve_workspace_path
abbreviateHomePath = abbreviate_home_path
workspaceTitleOf = workspace_title_of
