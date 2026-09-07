"""
1:1 parity test suite porting reference/packages/boot/app-boot/tests/hmr-config.spec.ts
Tests exact config and module paths watched by HMR, alias collapsing, serialization, and error normalization.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import os
import pathlib
import shutil
import sys
import tempfile
import time
from typing import List, Optional

import pytest

from dsh.cordis.context import Context
from dsh.cordis.hmr import Hmr
from dsh.cordis.loader import Loader
from dsh.cordis.timer import Timer


async def boot_hmr(dir_path: str, root: Optional[List[str]] = None, use_polling: Optional[bool] = None) -> Context:
    ctx = Context()
    norm_dir = os.path.abspath(dir_path)
    ctx.baseUrl = pathlib.Path(norm_dir).as_uri() + "/"
    await ctx.plugin(Loader)
    await ctx.plugin(Timer)
    hmr_cfg = {
        "root": root or [],
        "ignored": [],
        "debounce": 0,
    }
    if use_polling is not None:
        hmr_cfg["usePolling"] = use_polling
    await ctx.plugin(Hmr, hmr_cfg)
    return ctx


async def eventually(test_fn, message: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while not test_fn():
        if time.time() >= deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_observes_module_changes_when_watch_base_is_filesystem_alias():
    target = tempfile.mkdtemp(prefix="dsh-hmr-module-canonical-")
    alias = f"{target}-alias"
    alias_filename = os.path.join(alias, "module.ts")
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(target, alias)
    else:
        os.symlink(target, alias, target_is_directory=True)

    with open(alias_filename, "w", encoding="utf-8") as f:
        f.write("export const generation = 0\n")

    ctx = await boot_hmr(alias, ["."], True)
    filename = os.path.join(os.path.realpath(target), "module.ts")
    expected = pathlib.Path(filename).as_uri()

    has_calls = []

    def mock_has(url: str) -> bool:
        has_calls.append(url)
        return False

    ctx.loader.internal.loadCache.has = mock_has
    observed: List[str] = []
    ctx.on("hmr/change", lambda url: observed.append(url))

    try:
        deadline = time.time() + 20.0
        generation = 1
        while expected not in observed:
            if time.time() >= deadline:
                raise AssertionError(f"HMR did not observe {expected} through the alias; observed {observed}")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"export const generation = {generation}\n{' ' * generation}\n")
            await asyncio.sleep(0.25)
            generation += 1
        assert expected in has_calls
    finally:
        await ctx.fiber.dispose()
        if sys.platform == "win32":
            os.rmdir(alias)
        else:
            os.unlink(alias)
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.asyncio
async def test_collapses_filesystem_aliases_before_registering_exact_watch():
    target = tempfile.mkdtemp(prefix="dsh-hmr-canonical-")
    alias = f"{target}-alias"
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(target, alias)
    else:
        os.symlink(target, alias, target_is_directory=True)

    ctx = await boot_hmr(alias)
    try:
        await ctx.hmr.registerConfig("plugins.yml", lambda: None)
        with pytest.raises(Exception, match="config path already registered"):
            await ctx.hmr.registerConfig(os.path.join(os.path.realpath(target), "plugins.yml"), lambda: None)
    finally:
        await ctx.fiber.dispose()
        if sys.platform == "win32":
            os.rmdir(alias)
        else:
            os.unlink(alias)
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.asyncio
async def test_observes_add_change_and_unlink_outside_module_roots():
    dir_path = tempfile.mkdtemp(prefix="dsh-hmr-config-")
    filename = os.path.join(dir_path, "plugins.yml")
    ctx = await boot_hmr(dir_path)
    observed: List[str] = []
    try:
        def on_refresh():
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    observed.append(f.read())
            except FileNotFoundError:
                observed.append("missing")

        await ctx.hmr.registerConfig(filename, on_refresh)

        with open(filename, "w", encoding="utf-8") as f:
            f.write("one")
        await eventually(lambda: "one" in observed, "HMR did not observe config creation")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("two")
        await eventually(lambda: "two" in observed, "HMR did not observe config change")

        os.unlink(filename)
        await eventually(lambda: "missing" in observed, "HMR did not observe config removal")
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_observes_creation_when_config_parent_did_not_exist_at_registration():
    root = tempfile.mkdtemp(prefix="dsh-hmr-config-")
    dir_path = os.path.join(root, "later")
    filename = os.path.join(dir_path, "plugins.yml")
    ctx = await boot_hmr(root)
    observed: List[str] = []
    try:
        def on_refresh():
            with open(filename, "r", encoding="utf-8") as f:
                observed.append(f.read())

        await ctx.hmr.registerConfig(filename, on_refresh)
        os.makedirs(dir_path, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write("created")
        await eventually(lambda: "created" in observed, "HMR did not observe config creation under a new parent")
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_serializes_refreshes_and_waits_for_them_during_disposal():
    dir_path = tempfile.mkdtemp(prefix="dsh-hmr-config-")
    filename = os.path.join(dir_path, "plugins.yml")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("one")
    ctx = await boot_hmr(dir_path)

    loop = asyncio.get_running_loop()
    started = loop.create_future()
    release = loop.create_future()
    observed: List[str] = []
    active = [0]
    max_active = [0]

    try:
        async def on_refresh():
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            with open(filename, "r", encoding="utf-8") as f:
                observed.append(f.read())
            if len(observed) == 1:
                if not started.done():
                    started.set_result(None)
                await release
            active[0] -= 1

        dispose = await ctx.hmr.registerConfig(filename, on_refresh)
        await started
        with open(filename, "w", encoding="utf-8") as f:
            f.write("two")
        await asyncio.sleep(0.25)

        disposal = dispose()
        assert not disposal.disposed
        release.set_result(None)
        await disposal
        assert disposal.disposed
        assert max_active[0] == 1
        assert observed == ["one", "two"]
    finally:
        if not release.done():
            release.set_result(None)
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_normalizes_refresh_failures_and_broadcasts_them_without_escaping_watcher():
    dir_path = tempfile.mkdtemp(prefix="dsh-hmr-config-")
    filename = os.path.join(dir_path, "plugins.yml")
    ctx = await boot_hmr(dir_path)

    loop = asyncio.get_running_loop()
    failure = loop.create_future()
    failure_count = [0]

    try:
        def bad_observer(*args):
            raise RuntimeError("observer failed")

        def good_observer(failed_filename, error):
            failure_count[0] += 1
            if not failure.done():
                failure.set_result({"filename": failed_filename, "error": error})

        ctx.on("hmr/config-update-failed", bad_observer)
        ctx.on("hmr/config-update-failed", good_observer)

        def failing_refresh():
            raise RuntimeError("42")

        await ctx.hmr.registerConfig(filename, failing_refresh)
        with open(filename, "w", encoding="utf-8") as f:
            f.write("invalid")

        observed = await asyncio.wait_for(failure, timeout=10.0)
        assert observed["filename"] == filename
        assert isinstance(observed["error"], Exception)
        assert "42" in str(observed["error"])

        await asyncio.sleep(0.25)
        with open(filename, "w", encoding="utf-8") as f:
            f.write("invalid again")

        await eventually(lambda: failure_count[0] >= 2, "HMR stopped broadcasting after an observer rejected")
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)
