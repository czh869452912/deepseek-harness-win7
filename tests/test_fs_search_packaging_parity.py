import asyncio
import importlib.util
import os
import sys
import zipfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
PRESET_ROOT = ROOT / "dsh" / "presets"
EXPECTED_FS_SEARCH_PRESETS = {
    "code.yaml",
    "code/agent.cordis.yml",
    "cordis.yaml",
    "cordis/agent.cordis.yml",
    "creative.yaml",
    "creative/agent.cordis.yml",
    "standard.yaml",
    "standard/agent.cordis.yml",
}


class PresetLoader(yaml.SafeLoader):
    pass


PresetLoader.add_constructor(
    "tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node)
)


def _fs_search_rows(path):
    rows = yaml.load(path.read_text(encoding="utf-8"), Loader=PresetLoader)
    return [row for row in rows if row.get("name") == "@deepseek-ai/dsh-tool-fs-search"]


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_portable_under_test", ROOT / "scripts" / "build_portable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_shipped_fs_search_row_selects_the_pinned_over_cap_contract():
    found = set()
    composition_paths = list(PRESET_ROOT.glob("*.yaml")) + list(
        PRESET_ROOT.glob("*/agent.cordis.yml")
    )
    for path in composition_paths:
        rows = _fs_search_rows(path)
        if rows:
            found.add(path.relative_to(PRESET_ROOT).as_posix())
        for row in rows:
            assert row.get("config", {}).get("sampleOverCapGlobResults") is False

    assert found == EXPECTED_FS_SEARCH_PRESETS
    assert _fs_search_rows(PRESET_ROOT / "minimal.yaml") == []
    assert _fs_search_rows(PRESET_ROOT / "minimal" / "agent.cordis.yml") == []


def test_portable_stages_pinned_rg_and_zip_path_matches_runtime_resolver(tmp_path, monkeypatch):
    build = _load_build_module()
    fixture_root = tmp_path / "fixture"
    dist = fixture_root / "dist" / "dsh-win7-portable"
    shutil_target = fixture_root / "dsh" / "fs" / "tool_fs_search"
    shutil_target.mkdir(parents=True)
    source_search_core = ROOT / "dsh" / "fs" / "tool_fs_search" / "search_core.py"
    (shutil_target / "search_core.py").write_bytes(source_search_core.read_bytes())
    cli = fixture_root / "apps" / "cli"
    cli.mkdir(parents=True)
    (cli / "main.py").write_text("", encoding="utf-8")
    (fixture_root / "dsh.py").write_text("", encoding="utf-8")
    (fixture_root / "README.md").write_text("fixture", encoding="utf-8")

    pinned = fixture_root / "reference" / "deepseek-harness" / "node_modules" / ".pnpm"
    pinned = pinned / "@vscode+ripgrep-win32-x64@1.18.0" / "node_modules" / "@vscode"
    pinned = pinned / "ripgrep-win32-x64" / "bin" / "rg.exe"
    pinned.parent.mkdir(parents=True)
    expected_binary = Path(build.resolve_pinned_ripgrep_source(str(ROOT))).read_bytes()
    pinned.write_bytes(expected_binary)

    build.ROOT_DIR = str(fixture_root)
    build.DIST_DIR = str(dist)
    build.ZIP_OUTPUT = str(fixture_root / "dist" / "portable.zip")
    build.build_portable()

    staged = dist / "dsh" / "fs" / "tool_fs_search" / "bin" / "rg.exe"
    assert staged.read_bytes() == expected_binary

    with zipfile.ZipFile(build.ZIP_OUTPUT) as packaged:
        assert "dsh-win7-portable/dsh/fs/tool_fs_search/bin/rg.exe" in packaged.namelist()

    portable_core_path = dist / "dsh" / "fs" / "tool_fs_search" / "search_core.py"
    spec = importlib.util.spec_from_file_location("portable_search_core", portable_core_path)
    portable_search_core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portable_search_core)
    monkeypatch.setattr(portable_search_core.sys, "platform", "win32")
    monkeypatch.setattr(portable_search_core.shutil, "which", lambda _name: None)
    portable_search_core._rg_path_cache = None
    assert asyncio.run(portable_search_core.resolve_rg_path()) == str(staged.resolve())


def test_missing_pinned_rg_source_fails_loud(tmp_path):
    build = _load_build_module()
    with pytest.raises(FileNotFoundError, match="pinned @vscode/ripgrep-win32-x64@1.18.0"):
        build.resolve_pinned_ripgrep_source(str(tmp_path))
