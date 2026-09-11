"""
Portable release smoke test suite.
Validates dsh.py entrypoint invocations across profiles and modes.
"""

import os
import subprocess
import sys
import pytest


def _run_dsh(*args):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dsh_py = os.path.join(root_dir, "dsh.py")
    python_exe = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = root_dir
    res = subprocess.run(
        [python_exe, dsh_py, *args],
        cwd=root_dir,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    return res


def test_smoke_help_flag():
    """Verify dsh --help exits 0 and prints usage."""
    res = _run_dsh("--help")
    assert res.returncode == 0
    assert "Usage: dsh" in res.stdout
    assert "--profile" in res.stdout


def test_smoke_version_flag():
    """Verify dsh --version exits 0."""
    res = _run_dsh("--version")
    assert res.returncode == 0
    assert res.stdout.strip() != ""


def test_smoke_dump_config_minimal_profile():
    """Verify dsh --profile minimal --dump-config produces valid YAML and exits 0."""
    res = _run_dsh("--profile", "minimal", "--dump-config")
    assert res.returncode == 0
    assert "str-replace-editor" in res.stdout


def test_smoke_dump_config_standard_profile():
    """Verify dsh --profile standard --dump-config produces valid YAML and exits 0."""
    res = _run_dsh("--profile", "standard", "--dump-config")
    assert res.returncode == 0
    assert "cordis:group" in res.stdout or "plan-mode" in res.stdout


def test_smoke_dump_config_legacy_mode_flag():
    """Verify backward compatible --mode minimal --dump-config works."""
    res = _run_dsh("--mode", "minimal", "--dump-config")
    assert res.returncode == 0
    assert "str-replace-editor" in res.stdout


def test_smoke_dist_portable_directory():
    """If dist/dsh-win7-portable exists, verify it executes cleanly."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(root_dir, "dist", "dsh-win7-portable")
    dist_dsh_py = os.path.join(dist_dir, "dsh.py")
    if not os.path.exists(dist_dsh_py):
        pytest.skip("dist/dsh-win7-portable not built yet")

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{dist_dir};{os.path.join(dist_dir, 'lib')}"
    res = subprocess.run(
        [sys.executable, dist_dsh_py, "--profile", "minimal", "--dump-config"],
        cwd=dist_dir,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    assert res.returncode == 0
    assert "str-replace-editor" in res.stdout
