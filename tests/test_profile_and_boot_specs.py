import copy
import os
import tempfile
import yaml
import pytest

from dsh.cordis.profile import (
    BUILTIN_BUNDLES,
    BUILTIN_PROFILES,
    ComposedProfile,
    Profile,
    compose_profile,
    dump_config,
    home_patch_path,
    load_optional_patches,
    load_overlay_patches,
    prepare_profile,
    resolve_dsh_home,
    resolve_telemetry_patch,
)
from dsh.cordis.loader import apply_entry_patches


def test_prepare_profile_custom_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profiles", "custom-team")
        os.makedirs(profile_dir, exist_ok=True)
        patch_file = os.path.join(profile_dir, "cordis.patch.yml")
        with open(patch_file, "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "agent-team", "name": "@deepseek-ai/dsh-agent-team"}], f)

        prof = prepare_profile("custom-team", dsh_home=tmpdir)
        assert prof.name == "custom-team"
        assert len(prof.patches) == 1
        assert prof.patches[0]["id"] == "agent-team"


def test_telemetry_switch_resolution():
    # When row is present and switch is set
    patch = resolve_telemetry_patch("1", has_row=True)
    assert patch is not None
    assert patch["id"] == "session-telemetry-otel"
    assert patch["disabled"] is True

    # When switch is unset
    assert resolve_telemetry_patch(None, has_row=True) is None
    assert resolve_telemetry_patch("", has_row=True) is None

    # When row is not present
    assert resolve_telemetry_patch("1", has_row=False) is None


def test_apply_entry_patches_insert_and_modify():
    base = [
        {"id": "plugin-a", "name": "pkg-a", "config": {"key": "base_val"}},
        {"id": "plugin-b", "name": "pkg-b", "disabled": False},
    ]

    patches = [
        {"id": "plugin-a", "config": {"key": "patched_val"}},
        {"id": "plugin-b", "disabled": True},
        {"insert": [{"id": "plugin-c", "name": "pkg-c"}]},
    ]

    result = apply_entry_patches(base, patches)
    assert len(result) == 3
    assert result[0]["config"]["key"] == "patched_val"
    assert result[1]["disabled"] is True
    assert result[2]["id"] == "plugin-c"


def test_load_overlay_patches_validation():
    with tempfile.TemporaryDirectory() as tmpdir:
        patch_path = os.path.join(tmpdir, "my_overlay.yml")
        with open(patch_path, "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "llm", "config": {"temperature": 0.5}}], f)

        loaded = load_overlay_patches(patch_path)
        assert len(loaded) == 1
        assert loaded[0]["config"]["temperature"] == 0.5

        with pytest.raises(FileNotFoundError):
            load_overlay_patches(os.path.join(tmpdir, "nonexistent.yml"))


def test_composed_profile_all_patches_ordering():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Profile patch
        p_dir = os.path.join(tmpdir, "profiles", "test-p")
        os.makedirs(p_dir, exist_ok=True)
        with open(os.path.join(p_dir, "cordis.patch.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "layer-profile", "name": "profile"}], f)

        # Home patch
        with open(os.path.join(tmpdir, "cordis.patch.yml"), "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "layer-home", "name": "home"}], f)

        # Overlay patch
        ov_path = os.path.join(tmpdir, "ov.yml")
        with open(ov_path, "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "layer-overlay", "name": "overlay"}], f)

        composed = compose_profile("test-p", patch_files=[ov_path], dsh_home=tmpdir)
        all_p = composed.all_patches()
        ids = [p.get("id") for p in all_p]

        # Verify ordering: bundle layers -> profile patch -> home patch -> overlay patch
        assert "layer-profile" in ids
        assert "layer-home" in ids
        assert "layer-overlay" in ids
        assert ids.index("layer-profile") < ids.index("layer-home")
        assert ids.index("layer-home") < ids.index("layer-overlay")
