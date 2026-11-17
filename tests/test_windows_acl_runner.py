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


def test_isolated_runner_resolves_its_owned_sibling_without_host_import(tmp_path):
    workspace, temp = tmp_path / 'workspace', tmp_path / 'temporary'
    workspace.mkdir(); temp.mkdir()
    # CWD must not supply the helper, even with an isolated interpreter whose
    # sys.path excludes the trusted script directory (as embedded ._pth does).
    (workspace / 'windows_acl.py').write_text("raise RuntimeError('foreign helper')\n", encoding='utf-8')
    result = subprocess.run([sys.executable, '-I', '-B', str(RUNNER), '--workspace', str(workspace),
        '--temp', str(temp), '--mode', 'workspace-write', '--', sys.executable, '-I', '-c',
        "import sys; print('ISOLATED_RUNNER_READY'); sys.exit(23)"], cwd=str(workspace),
        capture_output=True, encoding='utf-8', timeout=20)
    assert result.returncode == 23 and result.stdout.strip() == 'ISOLATED_RUNNER_READY'
    assert not result.stderr


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


def test_restricted_child_initializes_without_account_in_inherited_default_acl(tmp_path, monkeypatch):
    """Model the hosted administrator's BA/SY/logon-read default object ACL."""
    workspace, temp = tmp_path / 'workspace', tmp_path / 'temp'
    workspace.mkdir()
    temp.mkdir()
    helper = tmp_path / 'default_acl_runner.py'
    helper.write_text('''
import ctypes as c
import sys
sys.path.insert(0, ROOT_LITERAL)
from dsh.sandbox.windows_acl import WinApi, SidAttributes, Groups, Access
from dsh.sandbox import windows_runner

original_init = WinApi.__init__
def initialize(api):
    original_init(api)
    original_create = api.CreateRestrictedToken
    def create(*args):
        assert args[1] == 0xd, 'LUA and WRITE_RESTRICTED must remain enabled'
        created = original_create(*args)
        if not created:
            return created
        token = c.cast(args[-1], c.POINTER(c.c_void_p)).contents
        groups = api.token_info(token, 2)
        count = c.c_ulong.from_buffer(groups).value
        logon = None
        for index in range(count):
            group = SidAttributes.from_buffer(groups, Groups.groups.offset + index * c.sizeof(SidAttributes))
            if group.attributes & 0xc0000000 == 0xc0000000:
                logon = group.sid
                break
        assert logon
        with api.sid('S-1-5-32-544') as administrators, api.sid('S-1-5-18') as system:
            entries = (Access * 3)(api.entry(administrators, permissions=0x10000000),
                                   api.entry(system, permissions=0x10000000),
                                   api.entry(logon, permissions=0xa0000000))
            for entry in entries:
                entry.inherit = 0
            acl = c.c_void_p()
            api.status(api.SetEntriesInAclW(3, entries, None, c.byref(acl)), 'SetEntriesInAclW fixture')
            try:
                api.check(api.SetTokenInformation(token, 6, c.byref(acl), c.sizeof(acl)), 'SetTokenInformation fixture')
            finally:
                api.LocalFree(acl)
        return created
    api.CreateRestrictedToken = create
WinApi.__init__ = initialize
code = windows_runner.main(sys.argv[1:])
sys.exit(code - 0x100000000 if code >= 0x80000000 else code)
'''.replace('ROOT_LITERAL', repr(str(RUNNER.parents[2]))), encoding='utf-8')
    monkeypatch.setattr(sys.modules[__name__], 'RUNNER', helper)
    result = run(workspace, temp, "import pathlib; pathlib.Path('owned').write_text('yes'); print('ACCOUNT_DEFAULT_ACL_READY')")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout.strip() == 'ACCOUNT_DEFAULT_ACL_READY'
    outside = tmp_path / 'outside.txt'
    result = run(workspace, temp, "import pathlib; pathlib.Path(%r).write_text('no')" % str(outside))
    assert result.returncode != 0 and 'PermissionError' in result.stderr
    assert not outside.exists()
    result = run(workspace, temp, "import pathlib; pathlib.Path('owned').write_text('no')", 'read-only')
    assert result.returncode != 0 and 'PermissionError' in result.stderr
    assert (workspace / 'owned').read_text(encoding='utf-8') == 'yes'


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
