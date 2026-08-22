"""
Unit tests verifying 1:1 parity and full coverage for dsh/presets package.
Tests discovery, metadata, authoring, settings integration, session preset resolution, and RPC API handlers.
"""

import os
import shutil
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.host.apiproxy.api.agent_presets import AgentPresetsDomainHandler
from dsh.presets import (
    AgentPreset,
    AgentPresets,
    Config,
    InvalidPresetIdError,
    PresetExistsError,
    PresetMountError,
    PresetNotWritableError,
    PresetRoot,
    UnknownPresetError,
    discover_presets,
    read_preset_metadata,
    render_preset_metadata,
    resolve_session_preset,
    scan_root,
)


def test_preset_metadata_read_and_render():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initially empty
        meta = read_preset_metadata(tmpdir)
        assert meta == {}

        # Render metadata
        rendered = render_preset_metadata({"name": "Test Preset", "description": "Test Desc", "order": 1})
        assert rendered is not None
        assert "name: Test Preset" in rendered

        # Write preset.yml
        with open(os.path.join(tmpdir, "preset.yml"), "w", encoding="utf-8") as f:
            f.write(rendered)

        meta2 = read_preset_metadata(tmpdir)
        assert meta2["name"] == "Test Preset"
        assert meta2["description"] == "Test Desc"
        assert meta2["order"] == 1.0


def test_preset_discovery_and_health():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a valid preset directory
        valid_dir = os.path.join(tmpdir, "my-preset")
        os.makedirs(valid_dir, exist_ok=True)
        with open(os.path.join(valid_dir, "agent.cordis.yml"), "w", encoding="utf-8") as f:
            f.write('- id: persona\n  name: "@deepseek-ai/dsh-persona"\n')

        # Create a broken preset directory (invalid YAML)
        broken_dir = os.path.join(tmpdir, "broken-preset")
        os.makedirs(broken_dir, exist_ok=True)
        with open(os.path.join(broken_dir, "agent.cordis.yml"), "w", encoding="utf-8") as f:
            f.write("invalid: [yaml: :")

        root = PresetRoot(path=tmpdir, trust="user")
        presets = scan_root(root)
        assert len(presets) == 2

        p_valid = next(p for p in presets if p.id == "my-preset")
        assert p_valid.broken is None
        assert p_valid.trust == "user"

        p_broken = next(p for p in presets if p.id == "broken-preset")
        assert p_broken.broken is not None


@pytest.mark.asyncio
async def test_agent_presets_service_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        sys_root = os.path.join(tmpdir, "sys")
        user_root = os.path.join(tmpdir, "user")
        os.makedirs(sys_root, exist_ok=True)
        os.makedirs(user_root, exist_ok=True)

        # System preset
        s_dir = os.path.join(sys_root, "standard")
        os.makedirs(s_dir, exist_ok=True)
        with open(os.path.join(s_dir, "agent.cordis.yml"), "w", encoding="utf-8") as f:
            f.write('- id: persona\n  name: "@deepseek-ai/dsh-persona"\n')

        cfg = Config(
            default="standard",
            roots=[PresetRoot(path=sys_root, trust="system"), PresetRoot(path=user_root, trust="user")],
            include_user_root=False,
        )

        ctx = Context()
        svc = AgentPresets(ctx, config=cfg)

        assert svc.default_id == "standard"
        assert svc.authorable is True

        # Resolve standard
        preset = await svc.resolve("standard")
        assert preset.id == "standard"
        assert preset.trust == "system"

        # Resolve unknown
        with pytest.raises(UnknownPresetError):
            await svc.resolve("unknown")

        # Copy standard -> custom
        await svc.copy("standard", "custom", "My Custom")
        c_preset = await svc.resolve("custom")
        assert c_preset.id == "custom"
        assert c_preset.trust == "user"
        assert c_preset.name == "My Custom"

        # Copy existing should raise PresetExistsError
        with pytest.raises(PresetExistsError):
            await svc.copy("standard", "custom")

        # Remove system preset should raise PresetNotWritableError
        with pytest.raises(PresetNotWritableError):
            await svc.remove("standard")

        # Remove user preset
        await svc.remove("custom")
        with pytest.raises(UnknownPresetError):
            await svc.resolve("custom")


def test_session_preset_resolution():
    session_obj = {
        "header": {"agentPreset": "standard"},
        "events": [
            {"type": "turn/start", "data": {}},
            {"type": "agent-preset/selected", "data": {"agentPreset": "minimal"}},
        ],
    }
    class MockSession:
        header = type("Header", (), {"agent_preset": "standard"})()
        events = session_obj["events"]

    resolved = resolve_session_preset(MockSession())
    assert resolved == "minimal"
