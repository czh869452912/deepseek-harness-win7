"""
Unit tests for dsh.identity subsystem.
"""

import os
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.identity import (
    ANONYMOUS_USER_ID_FILE_NAME,
    AnonymousUserId,
    apply_anonymous_user_id_invariant,
    get_or_create_anonymous_user_id,
    get_system_user,
    getOrCreateAnonymousUserId,
    resolve_author_identity,
)
from dsh.identity.anonymous_user_id import UUID_PATTERN, _memo


def test_anonymous_user_id_generation_and_persistence(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {"DSH_HOME": tmpdir}

        # Clear memo for test path
        expected_file = os.path.abspath(os.path.join(tmpdir, ANONYMOUS_USER_ID_FILE_NAME))
        _memo.pop(expected_file, None)

        uid1 = get_or_create_anonymous_user_id({"env": env})
        assert bool(UUID_PATTERN.match(uid1)) is True
        assert os.path.exists(expected_file)

        # File content check
        with open(expected_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        assert content == uid1

        # Second call returns memoized / persisted id
        uid2 = getOrCreateAnonymousUserId({"env": env})
        assert uid2 == uid1


def test_anonymous_user_id_corrupt_file_recovery(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {"DSH_HOME": tmpdir}
        expected_file = os.path.abspath(os.path.join(tmpdir, ANONYMOUS_USER_ID_FILE_NAME))
        _memo.pop(expected_file, None)

        # Write corrupt file
        with open(expected_file, "w", encoding="utf-8") as f:
            f.write("invalid-non-uuid-string\n")

        uid = get_or_create_anonymous_user_id({"env": env})
        assert bool(UUID_PATTERN.match(uid)) is True
        assert uid != "invalid-non-uuid-string"


def test_user_identity_and_author_resolution(monkeypatch):
    # Explicit user
    assert resolve_author_identity("alice") == "alice"
    assert resolve_author_identity("  bob  ") == "bob"

    # Environment user
    monkeypatch.setenv("USER", "devuser")
    assert resolve_author_identity() == "devuser"

    monkeypatch.delenv("USER", raising=False)
    monkeypatch.setenv("USERNAME", "winuser")
    assert resolve_author_identity() == "winuser"

    # Fallback to get_system_user
    sys_user = get_system_user()
    assert isinstance(sys_user, str)
    assert len(sys_user) > 0


def test_anonymous_user_id_invariant():
    ctx = Context()
    registered = []

    class MockInvariants:
        def register(self, pkg, fn):
            registered.append(pkg)
            return lambda: None

    ctx.set_service("invariants", MockInvariants())
    apply_anonymous_user_id_invariant(ctx)
    assert "@deepseek-ai/dsh-anonymous-user-id" in registered
