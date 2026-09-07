import os
import tempfile
import yaml
from dsh.cordis.profile import (
    compose_profile,
    dump_config,
    prepare_profile,
    resolve_dsh_home,
    home_patch_path,
    BUILTIN_PROFILES,
    BUILTIN_BUNDLES,
)


def test_prepare_builtin_profiles():
    for name in ("web", "headless", "standard", "minimal", "creative", "sdk", "acp", "sdk-minimal"):
        prof = prepare_profile(name)
        assert prof.name == name
        assert len(prof.bundles) >= 1


def test_compose_profile_4_layer_cascading():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create user home patch
        home_patch = os.path.join(tmpdir, "cordis.patch.yml")
        with open(home_patch, "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "tool-fs", "config": {"root": "C:/custom"}}], f)

        # Create overlay patch
        overlay_patch = os.path.join(tmpdir, "overlay.yml")
        with open(overlay_patch, "w", encoding="utf-8") as f:
            yaml.safe_dump([{"id": "tool-pwsh", "disabled": True}], f)

        composed = compose_profile("standard", patch_files=[overlay_patch], dsh_home=tmpdir)
        assert composed.profile.name == "standard"
        assert len(composed.bundle_patches) > 0
        assert len(composed.home_patches) == 1
        assert len(composed.overlays) == 1

        all_patches = composed.all_patches()
        # Ensure overlay appears last
        assert all_patches[-1]["id"] == "tool-pwsh"
        assert all_patches[-1]["disabled"] is True


def test_dump_config_output():
    # 1. Verify standard profile dump contains dsh-base tools and agent rows
    yaml_std = dump_config("standard")
    parsed_std = yaml.safe_load(yaml_std)
    assert isinstance(parsed_std, list)
    ids_std = [e.get("id") for e in parsed_std]
    assert "tools" in ids_std
    assert "agent" in ids_std

    # 2. Verify minimal profile produces exact 18-row standalone sdk-minimal tree without fake tools/agent
    yaml_min = dump_config("minimal")
    parsed_min = yaml.safe_load(yaml_min)
    assert isinstance(parsed_min, list)
    ids_min = [e.get("id") for e in parsed_min]
    assert "agent-spine" in ids_min
    assert "str-replace-editor" in ids_min
    assert "sessions" in ids_min
    assert len(ids_min) == 18
