"""
Unit tests for run_dump_config matching reference/apps/cli/tests and dump-config.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import tempfile
import yaml
import pytest

from dsh.boot.dump_config import run_dump_config


def test_dump_config_default_only():
    text = run_dump_config("headless", default_only=True)
    assert isinstance(text, str)
    assert "# ==" in text  # provenance comments
    assert "dsh-base" in text
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, list)
    assert len(parsed) > 0


def test_dump_config_with_overlays_and_custom_home():
    with tempfile.TemporaryDirectory() as tmpdir:
        home_patch = os.path.join(tmpdir, "cordis.patch.yml")
        with open(home_patch, "w", encoding="utf-8") as f:
            f.write("- insert:\n  - id: custom-home-entry\n    name: dummy-home\n")

        overlay_file = os.path.join(tmpdir, "overlay.yml")
        with open(overlay_file, "w", encoding="utf-8") as f:
            f.write("- insert:\n  - id: custom-overlay-entry\n    name: dummy-overlay\n")

        text = run_dump_config("headless", default_only=False, patches=[overlay_file], dsh_home=tmpdir)
        assert "custom-home-entry" in text
        assert "custom-overlay-entry" in text
        assert overlay_file in text

        parsed = yaml.safe_load(text)
        assert isinstance(parsed, list)
        entry_ids = [e.get("id") for e in parsed if isinstance(e, dict)]
        assert "custom-home-entry" in entry_ids
        assert "custom-overlay-entry" in entry_ids


def test_dump_config_official_presets_canonical():
    """X3: standard, minimal, and creative presets dump canonically without errors."""
    for preset_name in ("standard", "minimal", "creative"):
        text = run_dump_config(preset_name, default_only=True)
        assert isinstance(text, str)
        assert len(text) > 0


def test_cli_main_unknown_profile_outputs_clean_stderr_and_exits_1(monkeypatch, capsys):
    """X3: main() catches RuntimeError and outputs clean single-line error on stderr without traceback."""
    import sys
    from apps.cli.main import main
    monkeypatch.setattr(sys, "argv", ["dsh", "--profile", "nonexistent_preset_xyz", "--dump-config"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert 'dsh: profile "nonexistent_preset_xyz" does not exist' in captured.err
    assert "Traceback" not in captured.err
