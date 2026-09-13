"""
1:1 parity unit test suite for dsh/harness.py matching reference boot & app-boot.
Covers:
- T1: Missing preset file must fail loud (FileNotFoundError)
- T2: --patch overlay applies to the booted preset
- T3: User home patch layer applies at boot
- T6: dshHomePath resolves in context
- T9: Session query mounts dormant with open_at: never
- T10/T11: an activation failure fails loud, and the rejected startup has
  disposed the partial tree and left no pending lifecycle task
"""
import asyncio
import gc

import os
import tempfile
import warnings

import pytest

from dsh.harness import build_harness


def test_t1_build_harness_missing_preset_fails_loud():
    """T1: build_harness with nonexistent mode raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as exc:
        asyncio.run(build_harness(mode="nonexistent-preset-mode-12345"))
    assert "failed to read preset" in str(exc.value)


def test_t2_build_harness_applies_patch_overlay():
    """T2: build_harness loads and applies overlay patches."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        f.write(b"- id: str-replace-editor\n  config:\n    maxOutputChars: 99\n")
        overlay_path = f.name

    try:
        ctx = asyncio.run(build_harness(mode="minimal", patch_file=overlay_path))
        # Verify that overlay config took effect on str-replace-editor
        found = False
        for fiber in ctx.registry.list_fibers():
            if getattr(fiber.plugin, "id", None) == "str-replace-editor":
                assert getattr(fiber.plugin, "max_output_chars", None) == 99
                found = True
                break
        assert found
    finally:
        if os.path.exists(overlay_path):
            os.remove(overlay_path)


def test_t3_build_harness_missing_patch_file_fails_loud():
    """T3: build_harness with nonexistent patch_file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as exc:
        asyncio.run(build_harness(mode="minimal", patch_file="nonexistent_overlay_path.yaml"))
    assert "Overlay patch file not found" in str(exc.value) or "not found" in str(exc.value)


def test_t6_dsh_home_path_resolves():
    """T6: dshHomePath is provided on context and resolves against DSH_HOME."""
    ctx = asyncio.run(build_harness(mode="minimal"))
    assert hasattr(ctx, "dshHomePath") or hasattr(ctx, "dsh_home_path")
    fn = getattr(ctx, "dshHomePath", getattr(ctx, "dsh_home_path", None))
    assert callable(fn)
    p = fn("sessions")
    assert p.endswith("sessions")


def test_t9_session_query_mounted_dormant():
    """T9: SessionQueryPlugin mounts dormant with open_at: never in standard mode."""
    ctx = asyncio.run(build_harness(mode="standard"))
    sq = ctx.get("session_query")
    assert sq is not None
    assert getattr(sq, "open_at", None) == "never"


def test_t10_build_harness_fails_on_plugin_activation_failure(monkeypatch):
    """T10: build_harness raises RuntimeError if a plugin fails to activate (FAILED state)."""
    from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin

    def bad_apply(self, ctx, config=None):
        raise RuntimeError("boom during apply")

    monkeypatch.setattr(StrReplaceEditorPlugin, "apply", bad_apply)
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(build_harness(mode="minimal"))
    assert "did not activate" in str(exc_info.value) or "plugin(s) failed to activate" in str(exc_info.value)



@pytest.mark.asyncio
async def test_t11_build_harness_failure_disposes_the_partial_tree_and_leaves_no_pending_task(
    monkeypatch,
):
    """T11: a failed startup disposes the partial tree before the error escapes.

    Reference: `reference/packages/boot/app-boot/src/index.ts` `boot` catch --
    `await ctx.fiber.dispose()` runs before the failure is relabeled and thrown --
    and `reference/packages/boot/app-boot/tests/app-boot.spec.ts` 'disposes partial
    host setup and labels non-Error preparation failures', where the rejected boot
    still ran the effect disposer (`disposed === true`). `build_harness` is the
    port's config-tree boot equivalent, so its failure path owes the same
    settlement. The root fiber owns no parent-owned registration, so a
    synchronous `ctx.teardown()` only schedules the disposal and lets the fiber
    teardown tasks (`Fiber._await_quiescent`, `_unload` gathers, effect cleanups)
    outlive the raised error.
    """
    from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin

    seen = []

    def bad_apply(self, ctx, config=None):
        seen.append(ctx)
        raise RuntimeError("boom during apply")

    monkeypatch.setattr(StrReplaceEditorPlugin, "apply", bad_apply)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(RuntimeError) as exc_info:
            await build_harness(mode="minimal")
        # No checkpoint between the raise and these reads: the partial tree must
        # already be disposed when the failure escapes.
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        root = seen[0].root
        fibers = list(root.registry.list_fibers())
        tools = root.get("tools")
        settlements = root.fiber.settlement_tasks()
        gc.collect()

    assert "did not activate" in str(exc_info.value)
    assert seen, "the failing plugin never reached apply()"
    # Every mounted fiber, and the service it provided, went with the tree.
    assert fibers == []
    assert tools is None
    assert settlements == []
    # Nothing outlives the failed startup: no pending task, no unawaited
    # coroutine.
    assert pending == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
