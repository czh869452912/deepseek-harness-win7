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
