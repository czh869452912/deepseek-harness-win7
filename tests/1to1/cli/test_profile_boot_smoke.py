"""
Smoke test for run_profile in dsh/boot/profile_boot.py.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import os
import tempfile
import pytest

from dsh.boot.profile_boot import run_profile
from dsh.boot.profile import init_profile


@pytest.mark.asyncio
async def test_run_profile_smoke_and_app_exit():
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = os.path.join(tmpdir, "profiles", "test-prof")
        init_profile(profile_dir, [], "startup")

        res = await run_profile({
            "profile": "test-prof",
            "dsh_home": tmpdir,
            "wait_for_exit": False,
        })

        assert "ctx" in res
        assert "shutdown" in res

        ctx = res["ctx"]
        shutdown = res["shutdown"]
        from dsh.cordis.fiber import FiberState
        assert ctx.fiber.state == FiberState.ACTIVE

        # Trigger app exit with code 42
        exit_fn = getattr(ctx, "appExit", None)
        if exit_fn is not None:
            exit_fn(42)
        else:
            shutdown.shutdown(42)

        code = await shutdown.wait()
        assert code == 42
        assert shutdown.exit_code == 42
