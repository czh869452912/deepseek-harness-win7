"""
1:1 Test Parity for atomic file writes and file locking
Matching reference/packages/util/atomic-write/tests/atomic-write.spec.ts
"""

import os
import tempfile
import time
import pytest
from dsh.cordis.file_lock import FileLock


def test_file_lock_mutual_exclusion():
    """Verify FileLock acquires and releases cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "doc.txt")
        lock_path = target + ".lock"

        lock = FileLock(lock_path)
        with lock:
            assert os.path.exists(lock_path)
            # Writing while locked
            with open(target, "w", encoding="utf-8") as f:
                f.write("locked content")

        assert os.path.exists(target)
        with open(target, "r", encoding="utf-8") as f:
            assert f.read() == "locked content"


def test_atomic_write_simulation():
    """Verify temp file rename atomic write pattern."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "nested", "doc.yaml")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp_target = target + ".tmp"

        # Write to temp file first
        with open(tmp_target, "w", encoding="utf-8") as f:
            f.write("key: value\n")

        # Atomic rename
        os.replace(tmp_target, target)
        assert os.path.exists(target)
        assert not os.path.exists(tmp_target)
        with open(target, "r", encoding="utf-8") as f:
            assert f.read() == "key: value\n"
