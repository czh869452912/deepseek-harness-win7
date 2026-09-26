"""
1:1 parity suite for `@deepseek-ai/dsh-fs-sandbox` (`dsh/fs/fs_sandbox.py`).

Upstream is reference/packages/fs/fs-sandbox/tests/fs-sandbox.spec.ts plus
.../containment.spec.ts: the per-call policy fence on write/edit (read-only
denies, workspace-write contains, danger-full-access passes through), reads
always passing through, the capability fact, the containment matrix (`..`
traversal, absolute paths outside, symlink escapes), and the lexical plus
filesystem-identity containment mechanics.

Platform notes:
- the base lives under the user home, deliberately NOT the platform temp
  directory, because `workspace-write` grants the temp areas (parity with the
  bash runner) and an "outside" directory under them would be legitimately
  writable;
- a directory link is created through `dsh.boot.profile.create_symlink`, which
  publishes a Windows directory junction on the Windows 7 target (no
  SeCreateSymbolicLinkPrivilege required) and a symlink elsewhere; the
  containment outcome is the same on both.
"""

import os
import shutil
import tempfile
from typing import Any, Dict, Optional

import pytest

from dsh.boot.profile import create_symlink
from dsh.cordis.context import Context
from dsh.fs.fs_local import FsError, FsTarget
from dsh.fs.fs_sandbox import SandboxedFileSystem, is_path_under
from dsh.sandbox.sandbox_policy import SandboxPolicyService


def home_base() -> str:
    """A scratch base beside the user home, outside every temp grant."""
    return tempfile.mkdtemp(prefix=".dsh-fssbx-", dir=os.path.expanduser("~"))


class SandboxHarness:
    """One booted sandbox pair: policy service plus the enforcing backend."""

    def __init__(self) -> None:
        self.base = home_base()
        self.workspace = os.path.join(self.base, "ws")
        self.outside = os.path.join(self.base, "out")
        os.makedirs(self.workspace)
        os.makedirs(self.outside)
        self.ctx: Optional[Context] = None
        self.fs: Optional[SandboxedFileSystem] = None
        self.fiber: Any = None

    async def boot(self, mode: str) -> None:
        self.ctx = Context()
        await self.ctx.plugin(SandboxPolicyService, {"mode": mode, "workspaceRoot": self.workspace})
        self.fiber = await self.ctx.plugin(SandboxedFileSystem, {"cwd": self.workspace})
        self.fs = self.ctx.get("fs")

    async def dispose(self) -> None:
        if self.fiber is not None:
            await self.fiber.dispose()
            self.fiber = None
        shutil.rmtree(self.base, ignore_errors=True)


# --- the capability fact -----------------------------------------------------


@pytest.mark.asyncio
async def test_reports_the_deployment_default_mode():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        assert h.fs.sandboxMode == "workspace-write"
    finally:
        await h.dispose()


# --- read-only ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_denies_write_leaving_no_file_on_disk():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        path = os.path.join(h.workspace, "denied.txt")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(path), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
        assert not os.path.exists(path)
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_read_only_denies_edit_of_an_existing_file_and_the_content_is_unchanged():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        path = os.path.join(h.workspace, "file.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("original")
        with pytest.raises(FsError) as raised:
            await h.fs.editText(
                await h.fs.resolve(path),
                {"oldString": "original", "newString": "changed", "replaceAll": False},
            )
        assert raised.value.code == "FS_SANDBOX_DENIED"
        with open(path, encoding="utf-8") as f:
            assert f.read() == "original"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_read_only_allows_reads_because_every_mode_permits_reading():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        path = os.path.join(h.workspace, "readable.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("hello")
        assert await h.fs.readText(await h.fs.resolve(path)) == "hello"
    finally:
        await h.dispose()


# --- workspace-write containment --------------------------------------------


@pytest.mark.asyncio
async def test_a_write_under_the_workspace_lands():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        path = os.path.join(h.workspace, "nested", "ok.txt")
        outcome = await h.fs.writeText(await h.fs.resolve(path), "inside")
        assert outcome.operation == "create"
        with open(path, encoding="utf-8") as f:
            assert f.read() == "inside"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_write_to_the_platform_temp_area_lands():
    h = SandboxHarness()
    temp_dir = None
    try:
        await h.boot("workspace-write")
        temp_dir = tempfile.mkdtemp(prefix="dsh-fssbx-tmp-")
        path = os.path.join(temp_dir, "temp.txt")
        await h.fs.writeText(await h.fs.resolve(path), "temp")
        with open(path, encoding="utf-8") as f:
            assert f.read() == "temp"
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        await h.dispose()


@pytest.mark.asyncio
async def test_an_absolute_path_outside_the_workspace_is_denied_and_no_file_is_created():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        path = os.path.join(h.outside, "escape.txt")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(path), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
        assert not os.path.exists(path)
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_parent_traversal_out_of_the_workspace_is_denied():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        escaped = os.path.join(h.workspace, "..", "sibling-escape.txt")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(escaped), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
        assert not os.path.exists(escaped)
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_linked_directory_inside_the_workspace_pointing_out_is_denied():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        create_symlink(h.outside, os.path.join(h.workspace, "link"))
        path = os.path.join(h.workspace, "link", "f.txt")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(path), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
        assert not os.path.exists(os.path.join(h.outside, "f.txt"))
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_new_file_created_under_a_linked_out_directory_is_denied():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        create_symlink(h.outside, os.path.join(h.workspace, "link"))
        path = os.path.join(h.workspace, "link", "newdir", "deep.txt")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(path), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
        assert not os.path.exists(os.path.join(h.outside, "newdir"))
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_an_edit_outside_the_workspace_is_denied_and_the_original_is_untouched():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        path = os.path.join(h.outside, "file.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("original")
        with pytest.raises(FsError) as raised:
            await h.fs.editText(
                await h.fs.resolve(path),
                {"oldString": "original", "newString": "x", "replaceAll": False},
            )
        assert raised.value.code == "FS_SANDBOX_DENIED"
        with open(path, encoding="utf-8") as f:
            assert f.read() == "original"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_an_edit_inside_the_workspace_lands():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        path = os.path.join(h.workspace, "edit.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("original")
        outcome = await h.fs.editText(
            await h.fs.resolve(path),
            {"oldString": "original", "newString": "changed", "replaceAll": False},
        )
        assert outcome.after == "changed"
        with open(path, encoding="utf-8") as f:
            assert f.read() == "changed"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_mutates_the_freshly_checked_identity_not_a_stale_outside_target_key():
    # A target whose displayPath is inside the workspace but whose targetKey is
    # a STALE outside path - as if an ancestor link pointed out at the tool's
    # resolve() and was swapped in before the write. The fence re-resolves
    # displayPath (now inside) AND delegates with that fresh target, so the byte
    # lands inside and the stale outside path is never written.
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        inside_path = os.path.join(h.workspace, "landed.txt")
        stale_target = FsTarget(
            target_key=os.path.join(h.outside, "escaped.txt"),
            display_path=inside_path,
        )
        await h.fs.writeText(stale_target, "inside")
        with open(inside_path, encoding="utf-8") as f:
            assert f.read() == "inside"
        assert not os.path.exists(os.path.join(h.outside, "escaped.txt"))
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_the_workspace_root_itself_passes_the_fence_failing_only_on_file_type():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(h.workspace), "x")
        assert raised.value.code == "FS_NOT_REGULAR_FILE"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_workspace_root_that_is_the_filesystem_root_grants_writes_anywhere_on_that_volume():
    h = SandboxHarness()
    try:
        volume_root = os.path.splitdrive(h.base)[0] + os.sep
        ctx = Context()
        await ctx.plugin(SandboxPolicyService, {"mode": "workspace-write", "workspaceRoot": volume_root})
        fiber = await ctx.plugin(SandboxedFileSystem, {"cwd": h.workspace})
        root_fs = ctx.get("fs")
        try:
            path = os.path.join(h.base, "anywhere.txt")
            await root_fs.writeText(await root_fs.resolve(path), "anywhere")
            with open(path, encoding="utf-8") as f:
                assert f.read() == "anywhere"
        finally:
            await fiber.dispose()
    finally:
        await h.dispose()


# --- danger-full-access ------------------------------------------------------


@pytest.mark.asyncio
async def test_danger_full_access_writes_anywhere_unfenced():
    h = SandboxHarness()
    try:
        await h.boot("danger-full-access")
        path = os.path.join(h.outside, "free.txt")
        await h.fs.writeText(await h.fs.resolve(path), "free")
        with open(path, encoding="utf-8") as f:
            assert f.read() == "free"
    finally:
        await h.dispose()


# --- the per-call policy override (escalation) -------------------------------


@pytest.mark.asyncio
async def test_a_workspace_write_stamp_on_a_read_only_default_lets_a_contained_write_land_for_that_call_only():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        path = os.path.join(h.workspace, "escalated.txt")
        await h.fs.writeText(
            await h.fs.resolve(path),
            "granted",
            None,
            None,
            {"mode": "workspace-write", "workspaceRoot": h.workspace},
        )
        with open(path, encoding="utf-8") as f:
            assert f.read() == "granted"
        # A neighboring plain call still runs under the read-only default.
        with pytest.raises(FsError) as raised:
            await h.fs.writeText(await h.fs.resolve(os.path.join(h.workspace, "plain.txt")), "x")
        assert raised.value.code == "FS_SANDBOX_DENIED"
    finally:
        await h.dispose()


@pytest.mark.asyncio
async def test_a_danger_full_access_stamp_bypasses_the_fence_for_that_call():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        path = os.path.join(h.outside, "granted-full.txt")
        await h.fs.writeText(
            await h.fs.resolve(path),
            "full",
            None,
            None,
            {"mode": "danger-full-access", "workspaceRoot": h.workspace},
        )
        with open(path, encoding="utf-8") as f:
            assert f.read() == "full"
    finally:
        await h.dispose()


# --- registration and HMR safety ---------------------------------------------


@pytest.mark.asyncio
async def test_registers_as_the_filesystem_service_and_unregisters_cleanly_from_a_child_fiber():
    h = SandboxHarness()
    try:
        await h.boot("workspace-write")
        assert isinstance(h.ctx.get("fs"), SandboxedFileSystem)
        await h.fiber.dispose()
        assert h.ctx.get("fs") is None
        # Re-mount below the disposed one to prove no lingering registration.
        h.fiber = await h.ctx.plugin(SandboxedFileSystem, {"cwd": h.workspace})
        assert isinstance(h.ctx.get("fs"), SandboxedFileSystem)
    finally:
        await h.dispose()


# --- FsError identity --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_denial_is_a_structured_fs_error_distinct_from_a_host_permission_error():
    h = SandboxHarness()
    try:
        await h.boot("read-only")
        error = None
        try:
            await h.fs.writeText(await h.fs.resolve(os.path.join(h.workspace, "x.txt")), "x")
        except FsError as raised:  # noqa: BLE001 - the error identity is the assertion
            error = raised
        assert isinstance(error, FsError)
        assert error.code == "FS_SANDBOX_DENIED"
    finally:
        await h.dispose()


# --- containment mechanics ---------------------------------------------------


@pytest.mark.asyncio
async def test_containment_accepts_equal_paths_descendants_and_a_filesystem_root_boundary(tmp_path):
    base = str(tmp_path)
    volume_root = os.path.splitdrive(base)[0] + os.sep
    assert await is_path_under(base, base) is True
    assert await is_path_under(os.path.join(base, "child"), base) is True
    assert await is_path_under(base, volume_root) is True


@pytest.mark.asyncio
async def test_containment_uses_case_insensitive_lexical_comparison_for_windows_style_paths(tmp_path):
    base = str(tmp_path)
    assert await is_path_under(os.path.join(base.upper(), "child"), base.lower(), False) is True
    assert await is_path_under(os.path.join(base, "case-sensitive-child"), base, True) is True


@pytest.mark.asyncio
async def test_containment_recognizes_an_alias_equivalent_root_by_identity_for_a_missing_target(tmp_path):
    base = str(tmp_path)
    real_root = os.path.join(base, "real")
    alias_root = os.path.join(base, "alias")
    os.makedirs(real_root)
    create_symlink(real_root, alias_root)
    assert await is_path_under(os.path.join(os.path.realpath(real_root), "missing", "file.txt"), alias_root) is True


@pytest.mark.asyncio
async def test_containment_denies_unrelated_and_missing_roots(tmp_path):
    base = str(tmp_path)
    allowed = os.path.join(base, "allowed")
    outside = os.path.join(base, "outside")
    os.makedirs(allowed)
    os.makedirs(outside)
    assert await is_path_under(os.path.join(outside, "file.txt"), allowed) is False
    assert await is_path_under(os.path.join(outside, "file.txt"), os.path.join(base, "missing-root")) is False


@pytest.mark.asyncio
async def test_containment_treats_a_regular_file_path_segment_as_a_missing_target(tmp_path):
    base = str(tmp_path)
    allowed = os.path.join(base, "allowed")
    blocker = os.path.join(base, "blocker")
    os.makedirs(allowed)
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("not a directory")
    assert await is_path_under(os.path.join(blocker, "child.txt"), allowed) is False
