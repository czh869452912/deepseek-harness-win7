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
        assert ctx.get("appExit") is not None
        exit_fn = ctx.get("appExit")
        exit_fn(42)

        code = await shutdown.wait()
        assert code == 42
        assert shutdown.exit_code == 42


def test_portable_layout_bundle_resolution_smoke():
    """X4: In portable layout (no node_modules, only packages/bundle/*), bundle resolution succeeds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create portable layout in tmpdir
        anchor = os.path.join(tmpdir, "apps", "cli", "package.json")
        os.makedirs(os.path.dirname(anchor), exist_ok=True)
        with open(anchor, "w", encoding="utf-8") as f:
            f.write('{"name": "@deepseek-ai/dsh"}\n')

        base_pkg_dir = os.path.join(tmpdir, "packages", "bundle", "base")
        os.makedirs(base_pkg_dir, exist_ok=True)
        with open(os.path.join(base_pkg_dir, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "@deepseek-ai/dsh-base", "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}}\n')
        with open(os.path.join(base_pkg_dir, "cordis.patch.yml"), "w", encoding="utf-8") as f:
            f.write('- insert: [{id: base-plug, name: dummy}]\n')

        from dsh.boot.profile import resolve_bundle_dir, load_profile
        prof_dir = os.path.join(tmpdir, "profiles", "test-portable")
        init_profile(prof_dir, ["@deepseek-ai/dsh-base"], "startup")

        resolved = resolve_bundle_dir("dsh", "@deepseek-ai/dsh-base", anchor, prof_dir)
        assert os.path.normpath(resolved) == os.path.normpath(base_pkg_dir)

        loaded = load_profile("dsh", "test-portable", anchor, home=tmpdir)
        assert len(loaded.layers) == 1
        assert loaded.layers[0].packageName == "@deepseek-ai/dsh-base"
