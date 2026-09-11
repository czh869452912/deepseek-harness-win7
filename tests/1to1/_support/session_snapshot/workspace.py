"""
Capture readable, path-stable workspace state for recorded-session tests.
Ported 1:1 from reference packages/test-support/session-snapshot/src/workspace.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import base64
import os
from typing import Any, Dict, List, Optional, Set

EMPTY_WORKSPACE_MARKER = ".empty"


def _text_content(b: bytes) -> Optional[str]:
    if b"\x00" in b:
        return None
    try:
        text = b.decode("utf-8")
        if text.encode("utf-8") == b:
            return text
        return None
    except Exception:
        return None


def capture_workspace_snapshot(
    root: str,
    options: Optional[Dict[str, Any]] = None,
    ignored_root_entries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Capture one workspace without resolving links or depending on host path separators.
    """
    opts = options or {}
    ignored_list = list(opts.get("ignoredRootEntries", []))
    if ignored_root_entries is not None:
        ignored_list.extend(ignored_root_entries)
    ignored_set: Set[str] = set(ignored_list)

    def visit(directory: str, segments: List[str]) -> List[Dict[str, Any]]:
        try:
            entries = os.listdir(directory)
        except OSError:
            return []

        filtered = [
            e for e in entries
            if len(segments) > 0 or e not in ignored_set
        ]
        # Sort UTF-8 bytes ascending
        filtered.sort(key=lambda name: name.encode("utf-8"))

        captured: List[Dict[str, Any]] = []
        for name in filtered:
            child_segments = segments + [name]
            rel_path = "/".join(child_segments)
            abs_path = os.path.join(directory, name)

            if os.path.islink(abs_path):
                captured.append({
                    "path": rel_path,
                    "kind": "symlink",
                    "target": os.readlink(abs_path).replace("\\", "/"),
                })
            elif os.path.isdir(abs_path):
                children = visit(abs_path, child_segments)
                if len(children) == 0:
                    captured.append({"path": rel_path, "kind": "empty-directory"})
                else:
                    captured.extend(children)
            elif os.path.isfile(abs_path):
                with open(abs_path, "rb") as f:
                    data = f.read()
                content = _text_content(data)
                if content is None:
                    captured.append({
                        "path": rel_path,
                        "kind": "binary",
                        "base64": base64.b64encode(data).decode("ascii"),
                    })
                else:
                    captured.append({
                        "path": rel_path,
                        "kind": "text",
                        "content": content,
                    })
        return captured

    return visit(root, [])


def capture_expected_workspace_snapshot(
    expected_dir: str,
    options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    opts = dict(options or {})
    ignored = list(opts.get("ignoredRootEntries", []))
    if EMPTY_WORKSPACE_MARKER not in ignored:
        ignored.append(EMPTY_WORKSPACE_MARKER)
    opts["ignoredRootEntries"] = ignored
    raw = capture_workspace_snapshot(expected_dir, opts)
    return [e for e in raw if not e["path"].endswith(f"/{EMPTY_WORKSPACE_MARKER}") and e["path"] != EMPTY_WORKSPACE_MARKER]


captureWorkspaceSnapshot = capture_workspace_snapshot
captureExpectedWorkspaceSnapshot = capture_expected_workspace_snapshot
