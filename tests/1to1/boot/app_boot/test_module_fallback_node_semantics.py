"""
Node-equivalent resolution fixtures for the installation module-fallback
closure (`dsh/boot/profile.py: resolve_module_fallback_entries`).

These fixtures stage their own anchor trees, so the expectation is computed
from the fixture itself (what Node would resolve from the anchor) instead of
from the repository's workspace inventory. They pin the two properties the
workspace-layout stand-in must preserve:

* only packages reachable through declared `dependencies`/`peerDependencies`
  edges are healed — a package that merely exists in the workspace is not
  loader-visible, and a declared-but-absent dependency is skipped, not fatal;
* Node's `node_modules` lookup is nearest-first, so a copy installed beside the
  declaring package answers before the workspace layout does.
"""

import json
import os
import shutil
import tempfile
from typing import Any, Dict, Iterable, List, Set, Tuple

import pytest

from dsh.boot.profile import resolve_module_fallback_entries


def _write_manifest(directory: str, manifest: Dict[str, Any]) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "package.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return path


def _close(root: str) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _names(entries: Iterable[Dict[str, Any]]) -> Set[str]:
    return {entry["packageName"] for entry in entries}


def _entry(entries: Iterable[Dict[str, Any]], package_name: str) -> Dict[str, Any]:
    for entry in entries:
        if entry["packageName"] == package_name:
            return entry
    raise AssertionError(f"{package_name} is not part of the healed closure")


def test_a_declared_dependency_resolves_and_an_undeclared_workspace_package_stays_out():
    """
    Node heals what the anchor declares. The Python runtime's workspace layout
    stands in for the module graph, so a package the workspace carries but no
    reachable manifest declares must not become resolvable from the anchor.
    """
    root = tempfile.mkdtemp(prefix="dsh-closure-nodesem-")
    try:
        anchor = _write_manifest(os.path.join(root, "app"), {
            "name": "app",
            "dependencies": {"@scope/declared": "0.0.0", "child": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "declared"), {
            "name": "@scope/declared",
            "dependencies": {"nested": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "nested"), {"name": "nested"})
        _write_manifest(os.path.join(root, "packages", "group", "child"), {"name": "child"})
        # Present in the workspace, declared by nothing that is reachable.
        _write_manifest(os.path.join(root, "packages", "group", "unrelated"), {"name": "@scope/unrelated"})

        entries, names = resolve_module_fallback_entries(anchor)

        assert names == {"app", "@scope/declared", "nested", "child"}
        assert "@scope/unrelated" not in names
        assert len(entries) == len(names)
    finally:
        _close(root)


def test_a_declared_but_absent_dependency_is_skipped_not_fatal():
    """Node's own resolution finds nothing for an uninstalled dependency; the heal skips it."""
    root = tempfile.mkdtemp(prefix="dsh-closure-nodesem-")
    try:
        anchor = _write_manifest(os.path.join(root, "app"), {
            "name": "app",
            "dependencies": {"installed": "0.0.0", "absent": "0.0.0"},
            "peerDependencies": {"absent-peer": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "installed"), {"name": "installed"})

        _, names = resolve_module_fallback_entries(anchor)

        assert names == {"app", "installed"}
    finally:
        _close(root)


def test_node_modules_next_to_the_declaring_package_wins_over_the_workspace_layout():
    """
    Node resolves `<ancestor>/node_modules` nearest-first; the workspace layout
    is only the fallback for a workspace that carries no installed copy.
    """
    root = tempfile.mkdtemp(prefix="dsh-closure-nodesem-")
    try:
        anchor = _write_manifest(os.path.join(root, "app"), {
            "name": "app",
            "dependencies": {"shared": "0.0.0"},
        })
        installed = os.path.join(root, "app", "node_modules", "shared")
        _write_manifest(installed, {"name": "shared"})
        _write_manifest(os.path.join(root, "packages", "group", "shared"), {"name": "shared"})

        entries, _ = resolve_module_fallback_entries(anchor)

        assert os.path.realpath(_entry(entries, "shared")["packageDir"]) == os.path.realpath(installed)
    finally:
        _close(root)


def test_the_closure_walk_follows_the_declared_graph_from_each_package_anchor():
    """
    Every reachable package's own manifest anchors the next lookup, so a
    dependency declared only by a nested package is healed too — and its
    dependencies in turn.
    """
    root = tempfile.mkdtemp(prefix="dsh-closure-nodesem-")
    try:
        anchor = _write_manifest(os.path.join(root, "app"), {
            "name": "app",
            "dependencies": {"lib-a": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "lib-a"), {
            "name": "lib-a",
            "peerDependencies": {"lib-b": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "lib-b"), {
            "name": "lib-b",
            "dependencies": {"lib-c": "0.0.0"},
        })
        _write_manifest(os.path.join(root, "packages", "group", "lib-c"), {"name": "lib-c"})

        entries, names = resolve_module_fallback_entries(anchor)

        assert names == {"app", "lib-a", "lib-b", "lib-c"}
        for entry in entries:
            assert entry["kind"] == "symlink"
            manifest_path = os.path.join(entry["packageDir"], "package.json")
            with open(manifest_path, "r", encoding="utf-8") as handle:
                assert json.load(handle)["name"] == entry["packageName"]
    finally:
        _close(root)
