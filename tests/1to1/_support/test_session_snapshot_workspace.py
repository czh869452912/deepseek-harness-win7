"""
Unit tests for workspace snapshot capture.
Ported 1:1 from reference packages/test-support/session-snapshot/tests/workspace.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import shutil
import tempfile
import pytest

from .session_snapshot.workspace import (
    EMPTY_WORKSPACE_MARKER,
    captureExpectedWorkspaceSnapshot,
    captureWorkspaceSnapshot,
)


class TestWorkspaceSnapshots:
    @pytest.fixture
    def temp_dir(self):
        root = tempfile.mkdtemp(prefix="dsh-workspace-snapshot-")
        yield root
        shutil.rmtree(root, ignore_errors=True)

    def test_captures_readable_text_binary_bytes_links_and_empty_directories_in_path_order(self, temp_dir):
        with open(os.path.join(temp_dir, "a.txt"), "w", encoding="utf-8", newline="") as f:
            f.write("hello\n")
        with open(os.path.join(temp_dir, "b.bin"), "wb") as f:
            f.write(bytes([0xFF, 0x01]))
        os.makedirs(os.path.join(temp_dir, "empty"), exist_ok=True)

        can_symlink = True
        try:
            os.symlink("a.txt", os.path.join(temp_dir, "link"))
        except (OSError, NotImplementedError):
            can_symlink = False

        expected = [
            {"path": "a.txt", "kind": "text", "content": "hello\n"},
            {"path": "b.bin", "kind": "binary", "base64": "/wE="},
            {"path": "empty", "kind": "empty-directory"},
        ]
        if can_symlink:
            expected.append({"path": "link", "kind": "symlink", "target": "a.txt"})

        snapshot = captureWorkspaceSnapshot(temp_dir)
        if not can_symlink:
            snapshot = [s for s in snapshot if s.get("kind") != "symlink"]
        assert snapshot == expected

    def test_keeps_generic_marker_files_but_omits_declared_runtime_roots_and_the_expected_empty_marker(self, temp_dir):
        dsh_dir = os.path.join(temp_dir, ".dsh")
        os.makedirs(dsh_dir, exist_ok=True)
        with open(os.path.join(dsh_dir, "runtime.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(temp_dir, EMPTY_WORKSPACE_MARKER), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(temp_dir, "visible.txt"), "w", encoding="utf-8") as f:
            f.write("visible")

        assert captureWorkspaceSnapshot(temp_dir, ignored_root_entries=[".dsh"]) == [
            {"path": ".empty", "kind": "text", "content": ""},
            {"path": "visible.txt", "kind": "text", "content": "visible"},
        ]
        assert captureExpectedWorkspaceSnapshot(temp_dir) == [
            {"path": ".dsh/runtime.json", "kind": "text", "content": "{}"},
            {"path": "visible.txt", "kind": "text", "content": "visible"},
        ]

    def test_treats_nul_bearing_utf8_as_binary_workspace_state(self, temp_dir):
        with open(os.path.join(temp_dir, "nul.bin"), "wb") as f:
            f.write(bytes([0x61, 0x00, 0x62]))

        assert captureWorkspaceSnapshot(temp_dir) == [
            {"path": "nul.bin", "kind": "binary", "base64": "YQBi"},
        ]
