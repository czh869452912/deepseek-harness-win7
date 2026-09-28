"""Actual OS restriction, not an argv-only claim of confinement."""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from dsh.sandbox.windows_acl import capability_sid


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows restricted-token boundary")
RUNNER = Path(__file__).resolve().parents[1] / "dsh" / "sandbox" / "windows_runner.py"


def run(workspace, temp, code, mode="workspace-write", extra=()):
    return subprocess.run([sys.executable, str(RUNNER), "--workspace", str(workspace),
                           "--temp", str(temp), "--mode", mode] + list(extra) +
                          ["--", sys.executable, "-c", code], cwd=str(workspace),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", timeout=20)


def test_real_workspace_write_read_only_downgrade_and_private_temp(tmp_path):
    workspace = tmp_path / "workspace"
    temp = tmp_path / "temp"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    temp.mkdir()
    code = "import pathlib,os; pathlib.Path('ok').write_text('yes'); pathlib.Path(os.environ['TEMP'],'tmp').write_text('yes'); print(os.environ['TEMP'])"
    result = run(workspace, temp, code)
    assert result.returncode == 0, result.stderr
    assert (workspace / "ok").read_text() == "yes"
    assert not Path(result.stdout.strip()).exists()
    assert not list(temp.iterdir())
    result = run(workspace, temp, "import pathlib; pathlib.Path(%r).write_text('no')" % str(outside))
    assert result.returncode != 0 and "PermissionError" in result.stderr, result.stderr
    assert not outside.exists()
    result = run(workspace, temp, "import pathlib; pathlib.Path('ok').write_text('no')", "read-only")
    assert result.returncode != 0 and "PermissionError" in result.stderr, result.stderr
    assert (workspace / "ok").read_text() == "yes"


def test_restricted_child_can_create_piped_grandchild_and_mirrors_exit(tmp_path):
    workspace, temp = tmp_path / "workspace", tmp_path / "temp"
    workspace.mkdir()
    temp.mkdir()
    result = run(workspace, temp, "import subprocess,sys; r=subprocess.run([sys.executable,'-c','print(42)'],capture_output=True,text=True); print(r.stdout); sys.exit(r.returncode)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"
    result = run(workspace, temp, "import sys; sys.exit(19)")
    assert result.returncode == 19, result.stderr
    result = run(workspace, temp, "import ctypes; ctypes.windll.kernel32.ExitProcess(0xc0000005)")
    assert result.returncode == 0xc0000005, result.stderr


def test_runner_failures_never_execute_payload(tmp_path):
    workspace, temp = tmp_path / "workspace", tmp_path / "temp"
    workspace.mkdir()
    temp.mkdir()
    result = run(workspace, temp, "print('PAYLOAD')", extra=["--write-sid", "S-1-4-1-1", "--temp-write-sid", capability_sid(str(temp), True)])
    assert result.returncode == 127
    assert "windows-acl-run:" in result.stderr
    assert "PAYLOAD" not in result.stdout


@pytest.mark.parametrize("kill_runner", [False, True])
def test_job_closes_descendants_on_child_exit_or_runner_death(tmp_path, kill_runner):
    workspace, temp = tmp_path / "workspace", tmp_path / "temp"
    workspace.mkdir()
    temp.mkdir()
    descendant = "import time,pathlib; time.sleep(1); pathlib.Path('escaped').write_text('bad')"
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); print('started',flush=True); %s" % (descendant, "time.sleep(20)" if kill_runner else "pass")
    args = [sys.executable, str(RUNNER), "--workspace", str(workspace), "--temp", str(temp), "--mode", "workspace-write", "--", sys.executable, "-c", code]
    process = subprocess.Popen(args, cwd=str(workspace), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8")
    try:
        assert process.stdout.readline().strip() == "started"
        if kill_runner:
            process.kill()
        _, stderr = process.communicate(timeout=5)
        assert "windows-acl-run:" not in stderr
        time.sleep(1.1)
        assert not (workspace / "escaped").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    result = run(workspace, workspace, "print('PAYLOAD')")
    assert result.returncode == 127
    assert "outside" in result.stderr
    assert "PAYLOAD" not in result.stdout
