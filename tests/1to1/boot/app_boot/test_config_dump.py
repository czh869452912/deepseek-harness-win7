"""
1:1 Parity Tests for renderConfigDump
Port of reference/packages/boot/app-boot/tests/config-dump.spec.ts
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import re
import sys
import tempfile
import pytest
import yaml

from dsh.boot.app_boot import (
    loadOverlayPatches,
    path_to_file_url,
    renderConfigDump,
)

NAME = "dsh-test-bin"


def write_base(directory: str) -> str:
    base = os.path.join(directory, "base.yml")
    with open(base, "w", encoding="utf-8") as f:
        f.write(
            "- id: shared\n"
            "  name: ./noop.mjs\n"
            "  config:\n"
            "    value: base\n"
            "    key: !!js process.env.DSH_DUMP_SPEC\n"
            "- id: untouched\n"
            "  name: ./noop.mjs\n\n"
        )
    return base


def test_composes_overlay_layers_in_order():
    """Composes overlay layers in order, prints !!js verbatim, and labels each section with its source and patches."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        base = write_base(d)
        surface = os.path.join(d, "surface.yml")
        with open(surface, "w", encoding="utf-8") as f:
            f.write(
                "- id: shared\n"
                "  config:\n"
                "    value: surface\n"
                "    key: !!js process.env.DSH_DUMP_SPEC\n"
                "- insert:\n"
                "    - id: surface-extra\n"
                "      name: ./noop.mjs\n\n"
            )
        user = os.path.join(d, "user.yml")
        with open(user, "w", encoding="utf-8") as f:
            f.write(
                "- id: surface-extra\n"
                "  config:\n"
                "    value: user\n\n"
            )

        dump = renderConfigDump(
            NAME,
            base,
            [
                {"label": "surface.yml", "patches": loadOverlayPatches(NAME, surface)},
                {"label": "user.yml", "patches": loadOverlayPatches(NAME, user)},
            ],
            lambda line: None,
        )

        parsed = yaml.safe_load(dump)
        assert parsed == [
            {
                "id": "shared",
                "name": "./noop.mjs",
                "config": {"value": "surface", "key": {"__jsExpr": "process.env.DSH_DUMP_SPEC"}},
            },
            {"id": "untouched", "name": "./noop.mjs"},
            {
                "id": "surface-extra",
                "name": path_to_file_url(os.path.join(d, "noop.mjs")),
                "config": {"value": "user"},
            },
        ]

        assert "!!js process.env.DSH_DUMP_SPEC" in dump
        assert "# == base.yml, patched by surface.yml" in dump
        assert "# == base.yml\n- id: untouched" in dump
        assert "# == surface.yml, patched by user.yml\n- id: surface-extra" in dump
        assert dump.index("# == base.yml, patched by surface.yml") < dump.index("# == base.yml\n- id: untouched")


def test_groups_contiguous_rows_under_one_separator():
    """Groups contiguous rows with the same origin and patches under one separator."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        base = os.path.join(d, "base.yml")
        with open(base, "w", encoding="utf-8") as f:
            f.write(
                "- id: a\n"
                "  name: ./noop.mjs\n"
                "- id: b\n"
                "  name: ./noop.mjs\n\n"
            )
        dump = renderConfigDump(NAME, base, [], lambda line: None)
        assert len(re.findall(r"# == base\.yml", dump)) == 1
        assert "# == base.yml\n- id: a" in dump


def test_composes_all_layers_as_one_flattened_patch_list():
    """Composes all layers as one flattened patch list, exactly like boot()."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        base = os.path.join(d, "base.yml")
        with open(base, "w", encoding="utf-8") as f:
            f.write(
                "- id: g\n"
                "  name: ./group.mjs\n"
                "  group: true\n"
                "  config: []\n\n"
            )
        warnings = []
        dump = renderConfigDump(
            NAME,
            base,
            [
                {
                    "label": "a.yml",
                    "patches": [{"id": "g", "config": [{"id": "child", "name": "./noop.mjs", "config": {"v": 1}}]}],
                },
                {"label": "b.yml", "patches": [{"id": "child", "config": {"v": 2}}]},
            ],
            lambda line: warnings.append(line),
        )
        assert warnings == [f'{NAME}: [b.yml] patch: entry "child" not found']
        parsed = yaml.safe_load(dump)
        assert parsed[0]["config"][0]["config"]["v"] == 1
        assert "# == base.yml, patched by a.yml\n- id: g" in dump
        assert "b.yml\n- id: g" not in dump


def test_reports_absent_patch_through_warn():
    """Reports a patch whose target row is absent through warn with its layer label and keeps composing."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        base = write_base(d)
        overlay = os.path.join(d, "overlay.yml")
        with open(overlay, "w", encoding="utf-8") as f:
            f.write(
                "- id: only-on-another-surface\n"
                "  config:\n"
                "    value: ignored\n"
                "- id: shared\n"
                "  config:\n"
                "    value: patched\n\n"
            )
        warnings = []
        dump = renderConfigDump(
            NAME,
            base,
            [{"label": "overlay.yml", "patches": loadOverlayPatches(NAME, overlay)}],
            lambda line: warnings.append(line),
        )
        assert warnings == [f'{NAME}: [overlay.yml] patch: entry "only-on-another-surface" not found']
        parsed = yaml.safe_load(dump)
        assert parsed[0]["config"]["value"] == "patched"


def test_defaults_warn_sink_to_stderr(monkeypatch):
    """Defaults its warn sink to one stderr line per skipped patch."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        base = write_base(d)
        written = []
        monkeypatch.setattr(sys.stderr, "write", lambda s: written.append(s))
        renderConfigDump(NAME, base, [{"label": "x.yml", "patches": [{"id": "absent", "config": {}}]}])
        assert f'{NAME}: [x.yml] patch: entry "absent" not found\n' in written


def test_fails_loud_on_invalid_base_config():
    """Fails loud on a missing, unparsable, or non-array base config."""
    with tempfile.TemporaryDirectory(prefix="dsh-config-dump-") as d:
        absent = os.path.join(d, "absent.yml")
        with pytest.raises(Exception, match=rf"^{NAME}: failed to read config "):
            renderConfigDump(NAME, absent, [], lambda line: None)

        invalid = os.path.join(d, "invalid.yml")
        with open(invalid, "w", encoding="utf-8") as f:
            f.write("invalid: [unclosed\n")
        with pytest.raises(Exception, match=rf"^{NAME}: failed to parse config "):
            renderConfigDump(NAME, invalid, [], lambda line: None)

        scalar = os.path.join(d, "scalar.yml")
        with open(scalar, "w", encoding="utf-8") as f:
            f.write("id: not-a-list\n")
        with pytest.raises(Exception, match="must be a top-level YAML array of entries"):
            renderConfigDump(NAME, scalar, [], lambda line: None)
