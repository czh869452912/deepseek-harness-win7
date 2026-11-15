"""Actual restricted-child ownership and resources without nested Windows Jobs."""
import os
import sys

import pytest

from dsh.code_runtime.process import ProcessOwner
from dsh.cordis import Context
from dsh.sandbox.local import LocalSandboxProvider


@pytest.mark.skipif(os.name != 'nt', reason='Windows restricted-token Job ownership')
@pytest.mark.asyncio
async def test_confined_child_writes_only_its_workspace_and_cannot_break_its_job(tmp_path):
    workspace = tmp_path/'workspace'
    workspace.mkdir()
    outside = tmp_path/'outside'
    ctx = Context()
    await ctx.plugin(LocalSandboxProvider)
    provider = ctx.get('sandbox')
    memory = 128*1024*1024
    code = ("import sys,subprocess,pathlib\nsys.stdin.readline()\n"
            "pathlib.Path('allowed').write_text('yes',encoding='utf-8')\n"
            "try:\n    pathlib.Path(%r).write_text('no',encoding='utf-8')\n"
            "except PermissionError:\n    print('outside-denied',flush=True)\n"
            "try:\n    subprocess.Popen([sys.executable,'-c','pass'],creationflags=0x01000000)\n"
            "except OSError:\n    print('breakaway-denied',flush=True)\n" % str(outside))
    try:
        facts = provider.confine_process([getattr(sys,'_base_executable',sys.executable),'-c',code],
            dict(mode='workspace-write', workspaceRoot=str(workspace), sessionId='ptc'), memory)
        assert facts['enforcement'] == 'partial'
        owner = ProcessOwner(memory, str(workspace), private_control=True,
            argv=facts['argv'], windows_breakaway=facts['windowsJobBreakaway'])
        try:
            stdout, stderr = owner.process.communicate(b'go\n', timeout=15)
            assert owner.process.returncode == 0, stderr
            assert stdout.splitlines() == [b'outside-denied', b'breakaway-denied']
            assert (workspace/'allowed').read_text(encoding='utf-8') == 'yes'
            assert not outside.exists()
        finally:
            owner.close()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Windows restricted-token Job ownership')
@pytest.mark.asyncio
async def test_child_memory_limit_is_enforced_after_leaving_host_job(tmp_path):
    ctx = Context()
    await ctx.plugin(LocalSandboxProvider)
    provider = ctx.get('sandbox')
    memory = 64*1024*1024
    code = "import sys\nsys.stdin.readline()\nprint('entered',flush=True)\nvalue=bytearray(96*1024*1024)\nprint('unexpected',flush=True)"
    try:
        facts = provider.confine_process([getattr(sys,'_base_executable',sys.executable),'-c',code],
            dict(mode='read-only', workspaceRoot=str(tmp_path)), memory)
        owner = ProcessOwner(memory, str(tmp_path), private_control=True,
            argv=facts['argv'], windows_breakaway=facts['windowsJobBreakaway'])
        try:
            stdout, stderr = owner.process.communicate(b'go\n', timeout=15)
            assert owner.process.returncode != 0
            assert stdout.strip() == b'entered'
            assert b'MemoryError' in stderr and b'windows-acl-run:' not in stderr
        finally:
            owner.close()
    finally:
        await ctx.fiber.dispose()


def test_custom_runner_overlay_preserves_its_protocol_and_does_not_enable_breakaway():
    provider = LocalSandboxProvider(Context(), dict(runnerCommand=['custom'],
        runnerFailureSignatures=['custom failure']))
    policy = dict(mode='read-only', workspaceRoot=os.path.abspath(os.getcwd()))
    original = provider.confine(['program','argument'], policy)
    assert provider.confine_process(['program','argument'], policy, 1024) == original
    assert 'windowsJobBreakaway' not in original
    for value in (True, 0, -1, 1.5, sys.maxsize+1):
        with pytest.raises(ValueError, match='memory limit'):
            provider.confine_process(['program'], policy, value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows restricted-token Job ownership')
@pytest.mark.asyncio
async def test_host_owner_closure_kills_the_separate_restricted_child_job(tmp_path):
    import time
    ctx = Context()
    await ctx.plugin(LocalSandboxProvider)
    provider = ctx.get('sandbox')
    memory = 128*1024*1024
    marker = tmp_path/'escaped'
    child = "import time,pathlib;time.sleep(1);pathlib.Path(%r).write_text('bad')" % str(marker)
    code = ("import sys,subprocess,time\nsys.stdin.readline()\n"
            "subprocess.Popen([sys.executable,'-c',%r])\n"
            "print('started',flush=True)\ntime.sleep(60)" % child)
    owner = None
    try:
        facts = provider.confine_process([getattr(sys,'_base_executable',sys.executable),'-c',code],
            dict(mode='workspace-write', workspaceRoot=str(tmp_path), sessionId='ptc'), memory)
        owner = ProcessOwner(memory, str(tmp_path), private_control=True,
            argv=facts['argv'], windows_breakaway=facts['windowsJobBreakaway'])
        owner.process.stdin.write(b'go\n')
        owner.process.stdin.flush()
        assert owner.process.stdout.readline().strip() == b'started'
        owner.close()
        time.sleep(1.1)
        assert not marker.exists()
    finally:
        if owner is not None:
            owner.close()
            for stream in (owner.process.stdin, owner.process.stdout, owner.process.stderr):
                stream.close()
        await ctx.fiber.dispose()
