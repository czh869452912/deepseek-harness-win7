import os
import json
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


def test_creative_profile_mounts_its_native_bundle_over_original_composition():
    from dsh.boot.profile import PROFILE_TEMPLATES

    assert "patches" not in PROFILE_TEMPLATES["creative"]
    assert BUILTIN_PROFILES["creative"]["patches"] == []
    assert PROFILE_TEMPLATES['creative']['bundles'] == PROFILE_TEMPLATES['standard']['bundles'] + ['@deepseek-win7/dsh-creative']
    assert [row['name'] for row in BUILTIN_BUNDLES['dsh-creative'][0]['insert']] == [
        '@deepseek-ai/dsh-cordis-host-runner', '@deepseek-ai/dsh-tool-cordis']

    preset_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dsh", "presets", "creative.yaml")
    with open(preset_path, "r", encoding="utf-8") as f:
        rows = yaml.safe_load(f)
    manager_rows = [r for r in rows if isinstance(r, dict) and r.get("name") == "@deepseek-ai/dsh-cordis-manager"]
    assert len(manager_rows) == 1


def test_existing_creative_default_upgrades_without_overwriting_user_patches():
    from dsh.boot.profile import init_profile, load_profile, PROFILE_TEMPLATES
    from dsh.boot.profile_boot import INSTALL_ANCHOR
    with tempfile.TemporaryDirectory() as home:
        profile_dir = os.path.join(home, 'profiles', 'creative')
        init_profile(profile_dir, PROFILE_TEMPLATES['standard']['bundles'], 'startup')
        patch = os.path.join(profile_dir, 'cordis.patch.yml')
        rows = [{'id': 'system-prompt', 'config': {'persona': 'Keep my persona'}}]
        with open(patch, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(rows, stream)
        loaded = load_profile('dsh', 'creative', INSTALL_ANCHOR, home)
        assert [layer.packageName for layer in loaded.layers] == PROFILE_TEMPLATES['creative']['bundles']
        assert loaded.patches == rows
        with open(os.path.join(profile_dir, 'package.json'), encoding='utf-8') as stream:
            manifest = json.load(stream)
        manifest['dsh']['profile']['bundles'] = ['@deepseek-ai/dsh-base']
        with open(os.path.join(profile_dir, 'package.json'), 'w', encoding='utf-8') as stream:
            json.dump(manifest, stream)
        customized = load_profile('dsh', 'creative', INSTALL_ANCHOR, home)
        assert [layer.packageName for layer in customized.layers] == ['@deepseek-ai/dsh-base']
        assert customized.patches == rows


def test_native_install_anchor_uses_the_shipped_cli_identity():
    from pathlib import Path
    from dsh.boot.profile_boot import INSTALL_ANCHOR
    root = Path(__file__).resolve().parents[1]
    assert Path(INSTALL_ANCHOR) == root / 'apps/cli/package.json'
    assert Path(INSTALL_ANCHOR).read_bytes() == (root / 'reference/apps/cli/package.json').read_bytes()
    manifests = list((root / 'reference/vendor').glob('*/package.json'))
    assert manifests
    for manifest in manifests:
        for path in (manifest, manifest.with_name('LICENSE')):
            copied = root / path.relative_to(root / 'reference')
            assert copied.read_bytes() == path.read_bytes()


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
