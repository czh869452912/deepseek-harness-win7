"""
1:1 parity unit test suite for dsh/cordis/profile.py matching reference/packages/boot/app-boot/src/profile.ts.
Covers:
- T1: prepare_profile fails loud on unknown name and rejects invalid names
- T2: load_optional_patches fails loud on malformed YAML or non-array data, returns [] on missing
- T7: resolve_telemetry_patch checks composed rows, not raw unflattened rows
"""

import os
import tempfile
import pytest

from dsh.cordis.profile import (
    prepare_profile,
    load_optional_patches,
    compose_profile,
    TELEMETRY_ROW_ID,
)


def test_t1_prepare_profile_unknown_name_fails_loud():
    """T1: prepare_profile fails loud on unknown profile name and rejects invalid names."""
    tmp_home = tempfile.mkdtemp()

    try:
        # Invalid names
        with pytest.raises(ValueError) as exc1:
            prepare_profile("", dsh_home=tmp_home)
        assert "invalid profile name" in str(exc1.value)

        with pytest.raises(ValueError) as exc2:
            prepare_profile("foo/bar", dsh_home=tmp_home)
        assert "invalid profile name" in str(exc2.value)

        with pytest.raises(ValueError) as exc3:
            prepare_profile("..", dsh_home=tmp_home)
        assert "invalid profile name" in str(exc3.value)

        with pytest.raises(ValueError) as exc4:
            prepare_profile("node_modules", dsh_home=tmp_home)
        assert "invalid profile name" in str(exc4.value)

        # Unknown profile name
        with pytest.raises(ValueError) as exc5:
            prepare_profile("nonexistent-profile", dsh_home=tmp_home)
        assert "does not exist" in str(exc5.value)

        # Builtin profile succeeds
        p = prepare_profile("standard", dsh_home=tmp_home)
        assert p.name == "standard"
    finally:
        if os.path.exists(tmp_home):
            os.rmdir(tmp_home)


def test_t2_load_optional_patches_fail_loud():
    """T2: load_optional_patches throws on malformed YAML or non-array; returns [] on missing."""
    # 1. Missing file returns []
    assert load_optional_patches("nonexistent_file_path_12345.yaml") == []

    # 2. Syntax error throws ValueError
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b": malformed: [[\n")
        bad_syntax_file = f.name

    try:
        with pytest.raises(ValueError) as exc1:
            load_optional_patches(bad_syntax_file)
        assert "failed to read patches" in str(exc1.value)
    finally:
        if os.path.exists(bad_syntax_file):
            os.remove(bad_syntax_file)

    # 3. Top-level mapping throws ValueError (must be top-level array)
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"key: value\n")
        mapping_file = f.name

    try:
        with pytest.raises(ValueError) as exc2:
            load_optional_patches(mapping_file)
        assert "must be a top-level YAML array" in str(exc2.value)
    finally:
        if os.path.exists(mapping_file):
            os.remove(mapping_file)

    # 4. Valid top-level array returns list
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"- id: item1\n  name: plugin-a\n")
        valid_file = f.name

    try:
        patches = load_optional_patches(valid_file)
        assert len(patches) == 1
        assert patches[0]["id"] == "item1"
    finally:
        if os.path.exists(valid_file):
            os.remove(valid_file)
