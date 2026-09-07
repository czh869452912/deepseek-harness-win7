"""
1:1 parity test suite porting reference/packages/boot/app-boot/tests/user-patches.spec.ts
Tests user patch-layer behavior: optional patch-list loader, boot() applying user layer,
and transactional live HMR watching.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import inspect
import os
import shutil
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

import pytest

from dsh.boot.app_boot import (
    PROFILE_PATCH_FILENAME,
    boot,
    load_optional_patches,
    path_to_file_url,
    watch_user_patches,
)
from dsh.cordis.context import Context
from dsh.cordis.hmr import HmrService
from dsh.cordis.include import Include
from dsh.cordis.loader import Loader
from dsh.cordis.timer import TimerService

NAME = "dsh-test-bin"


def tmp() -> str:
    return tempfile.mkdtemp(prefix="dsh-user-patches-")


async def eventually(test: Callable[[], bool], message: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while not test():
        if time.time() >= deadline:
            raise TimeoutError(message)
        await asyncio.sleep(0.02)


def write_tree(dir_path: str) -> str:
    with open(os.path.join(dir_path, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write(
            'export const name = "noop"\n'
            'export function apply(_ctx, config = {}) {\n'
            '  if (config.fail) throw new Error("candidate config failed");\n'
            '}\n'
        )
    config_path = os.path.join(dir_path, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("- id: noop\n  name: ./noop.mjs\n  config:\n    value: base\n")
    return config_path


def entry_config(ctx: Context, entry_id: str) -> Any:
    for entry in ctx.loader.entries():
        if entry.options.get("id") == entry_id:
            return entry.options.get("config")
    return None


# ==============================================================================
# 1. loadOptionalPatches
# ==============================================================================

def test_returns_none_when_no_user_patch_file_exists():
    os.environ.pop("DSH_HOME", None)
    res = load_optional_patches(NAME, os.path.join(tmp(), PROFILE_PATCH_FILENAME))
    assert res is None


def test_parses_a_patch_list_and_preserves_js_expressions_as_loader_expression_nodes():
    os.environ.pop("DSH_HOME", None)
    dir_path = tmp()
    patch_path = os.path.join(dir_path, PROFILE_PATCH_FILENAME)
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(
            "- id: agent-loop\n"
            "  name: '@deepseek-ai/dsh-agent-loop'\n"
            "  config:\n"
            "    model: !!js process.env.DSH_SPEC_MODEL\n"
            "- insert:\n"
            "    - id: llm\n"
            "      name: '@deepseek-ai/dsh-llm-pi-ai'\n\n"
        )
    patches = load_optional_patches(NAME, patch_path)
    assert patches is not None
    assert len(patches) == 2
    assert patches[0]["id"] == "agent-loop"
    assert patches[0]["config"] == {"model": {"__jsExpr": "process.env.DSH_SPEC_MODEL"}}
    assert len(patches[1].get("insert", [])) == 1


def test_anchors_inserted_relative_plugins_to_the_patch_file_and_keeps_assertion_names_literal():
    os.environ.pop("DSH_HOME", None)
    dir_path = tmp()
    patch_path = os.path.join(dir_path, PROFILE_PATCH_FILENAME)
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(
            "- id: existing\n"
            "  name: ./assertion.mjs\n"
            "- insert:\n"
            "    - id: rule\n"
            "      name: ./rule.mjs\n"
            "    - id: nested\n"
            "      name: cordis:group\n"
            "      group: true\n"
            "      config:\n"
            "        - id: child\n"
            "          name: ../child.mjs\n\n"
        )
    patches = load_optional_patches(NAME, patch_path)
    assert patches is not None
    assert patches[0].get("name") == "./assertion.mjs"
    rule_url = path_to_file_url(os.path.abspath(os.path.join(dir_path, "rule.mjs")))
    child_url = path_to_file_url(os.path.abspath(os.path.join(dir_path, "..", "child.mjs")))
    assert patches[1]["insert"][0]["name"] == rule_url
    assert patches[1]["insert"][1]["config"][0]["name"] == child_url


def test_fails_loud_on_an_unreadable_file():
    os.environ.pop("DSH_HOME", None)
    dir_path = tmp()
    # Directory present with patch filename: unreadable as a file
    os.mkdir(os.path.join(dir_path, PROFILE_PATCH_FILENAME))
    with pytest.raises(RuntimeError, match=rf"^{NAME}: failed to read patches "):
        load_optional_patches(NAME, os.path.join(dir_path, PROFILE_PATCH_FILENAME))


def test_fails_loud_on_unparsable_yaml_and_on_a_js_tag_with_no_expression_body():
    os.environ.pop("DSH_HOME", None)
    dir_path = tmp()
    patch_path = os.path.join(dir_path, PROFILE_PATCH_FILENAME)
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write("invalid: [unclosed\n")
    with pytest.raises(RuntimeError, match=rf"^{NAME}: failed to parse patches "):
        load_optional_patches(NAME, patch_path)

    with open(patch_path, "w", encoding="utf-8") as f:
        f.write("- id: x\n  config:\n    a: !!js\n")
    with pytest.raises(RuntimeError, match=rf"^{NAME}: failed to parse patches "):
        load_optional_patches(NAME, patch_path)


def test_fails_loud_when_the_file_is_not_a_top_level_array_or_an_entry_is_not_an_object():
    os.environ.pop("DSH_HOME", None)
    dir_path = tmp()
    patch_path = os.path.join(dir_path, PROFILE_PATCH_FILENAME)
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write("id: not-a-list\n")
    with pytest.raises(RuntimeError, match="must be a top-level YAML array of loader patch entries"):
        load_optional_patches(NAME, patch_path)

    with open(patch_path, "w", encoding="utf-8") as f:
        f.write("- just-a-string\n")
    with pytest.raises(RuntimeError, match=rf"{NAME}: patches entry 1 in"):
        load_optional_patches(NAME, patch_path)


# ==============================================================================
# 2. Loader config interpolation
# ==============================================================================

@pytest.mark.asyncio
async def test_keeps_includes_config_literal_a_nested_rows_js_belongs_to_that_rows_fiber():
    dir_path = tmp()
    with open(os.path.join(dir_path, "reader.mjs"), "w", encoding="utf-8") as f:
        f.write(
            'export const name = "reader"\n'
            'export function apply(ctx, config) {\n'
            '  const val = (config && typeof config === "object") ? config.value : config;\n'
            '  ctx.provide("observedValue", val);\n'
            '}\n'
        )
    with open(os.path.join(dir_path, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: reader\n  name: ./reader.mjs\n")

    ctx = Context()
    await ctx.plugin(Loader)
    ctx.loader.builtins["include"] = Include
    ctx.provide("answer", 42)
    try:
        await ctx.loader.create({
            "name": "cordis:include",
            "config": {
                "path": path_to_file_url(os.path.join(dir_path, "cordis.yml")),
                "patches": [
                    {
                        "id": "reader",
                        "name": "./reader.mjs",
                        "config": {"value": {"__jsExpr": "ctx.get('answer')"}},
                    }
                ],
            },
        })
        await ctx.loader.wait()
        reader = next(entry for entry in ctx.loader.entries() if entry.options.get("id") == "reader")
        assert reader.options.get("config") == {"value": {"__jsExpr": "ctx.get('answer')"}}
        assert ctx.get("observedValue") == 42
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_waits_for_row_injections_before_resolving_js_and_resolves_again_after_provider_replacement():
    dir_path = tmp()
    with open(os.path.join(dir_path, "provider.mjs"), "w", encoding="utf-8") as f:
        f.write(
            'export const name = "provider"\n'
            'export function apply(ctx, config) { ctx.provide("phaseOne", config); }\n'
        )
    with open(os.path.join(dir_path, "reader.mjs"), "w", encoding="utf-8") as f:
        f.write(
            'export const name = "reader"\n'
            'export const inject = ["phaseOne"]\n'
            'export function apply(ctx, config) { ctx.provide("readerResult", config); }\n'
        )
    with open(os.path.join(dir_path, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("[]\n")

    composition = [
        {
            "insert": [
                {
                    "id": "reader",
                    "name": "./reader.mjs",
                    "inject": ["phaseOne"],
                    "config": {
                        "value": {
                            "__jsExpr": 'ctx.phaseOne.fail ? (() => { throw new Error("rejected provider") })() : ctx.phaseOne.value'
                        }
                    },
                },
                {"id": "provider", "name": "./provider.mjs", "config": {"value": "first"}},
            ]
        }
    ]

    ctx = await boot(NAME, os.path.join(dir_path, "cordis.yml"), composition)
    try:
        assert ctx.get("readerResult") == {"value": "first"}
        provider = next(entry for entry in ctx.loader.entries() if entry.options.get("id") == "provider")
        assert provider is not None

        await provider.update({"disabled": True})
        await ctx.loader.wait()
        assert ctx.get("readerResult") is None

        await provider.update({"config": {"value": "second"}})
        await provider.update({"disabled": False})
        await ctx.loader.wait()
        assert ctx.get("readerResult") == {"value": "second"}

        await provider.update({"disabled": True})
        await provider.update({"config": {"fail": True}})
        await provider.update({"disabled": False})
        with pytest.raises(Exception, match="rejected provider"):
            await ctx.loader.wait()
        assert ctx.get("readerResult") is None

        await provider.update({"disabled": True})
        await provider.update({"config": {"value": "recovered"}})
        await provider.update({"disabled": False})
        await ctx.loader.wait()
        assert ctx.get("readerResult") == {"value": "recovered"}
    finally:
        await ctx.fiber.dispose()


# ==============================================================================
# 3. Loader entry disabled interpolation
# ==============================================================================

@pytest.mark.asyncio
async def test_evaluates_a_js_disabled_expression_against_the_loader_context():
    dir_path = tmp()
    with open(os.path.join(dir_path, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply() {}\n')
    with open(os.path.join(dir_path, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write(
            "- id: expr-off\n"
            "  name: ./noop.mjs\n"
            "  disabled: !!js process.version.length > 0\n"
            "- id: expr-on\n"
            "  name: ./noop.mjs\n"
            "  disabled: !!js process.version.length === 0\n\n"
        )
    ctx = await boot(NAME, os.path.join(dir_path, "cordis.yml"))
    try:
        off = next(entry for entry in ctx.loader.entries() if entry.options.get("id") == "expr-off")
        on = next(entry for entry in ctx.loader.entries() if entry.options.get("id") == "expr-on")
        assert off.disabled is True
        assert off.fiber is None
        assert on.disabled is False
        assert on.fiber is not None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_keeps_the_raw_expression_in_the_options_so_write_back_preserves_the_js_form():
    dir_path = tmp()
    with open(os.path.join(dir_path, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply() {}\n')
    with open(os.path.join(dir_path, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write('- id: expr\n  name: ./noop.mjs\n  disabled: !!js process.platform === "win32"\n')

    ctx = await boot(NAME, os.path.join(dir_path, "cordis.yml"))
    try:
        entry = next(item for item in ctx.loader.entries() if item.options.get("id") == "expr")
        assert entry.options.get("disabled") == {"__jsExpr": 'process.platform === "win32"'}
        import sys
        assert entry.disabled is (sys.platform.startswith("win"))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_re_evaluates_when_update_replaces_the_expression_mounting_and_unmounting():
    dir_path = tmp()
    with open(os.path.join(dir_path, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply() {}\n')
    with open(os.path.join(dir_path, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write('- id: expr\n  name: ./noop.mjs\n  disabled: !!js process.version.length === 0\n')

    ctx = await boot(NAME, os.path.join(dir_path, "cordis.yml"))
    try:
        entry = next(item for item in ctx.loader.entries() if item.options.get("id") == "expr")
        assert entry.disabled is False
        assert entry.fiber is not None

        disabled_true = {"__jsExpr": "process.version.length > 0"}
        disabled_false = {"__jsExpr": "process.version.length === 0"}

        await entry.update({"disabled": disabled_true})
        assert entry.disabled is True
        assert entry.fiber is None

        await entry.update({"disabled": disabled_false})
        assert entry.disabled is False
        assert entry.fiber is not None
    finally:
        await ctx.fiber.dispose()


# ==============================================================================
# 4. boot with user patches & watching
# ==============================================================================

@pytest.mark.asyncio
async def test_applies_id_targeted_overrides_inserts_and_interpolates_js_from_the_environment():
    dir_path = tmp()
    user_dir = tmp()
    with open(os.path.join(user_dir, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write(
            'export function apply(_ctx, config = {}) {\n'
            '  if (config.fail) throw new Error("candidate config failed");\n'
            '}\n'
        )
    with open(os.path.join(user_dir, PROFILE_PATCH_FILENAME), "w", encoding="utf-8") as f:
        f.write(
            "- id: noop\n"
            "  name: ./noop.mjs\n"
            "  config:\n"
            "    value: !!js process.env.DSH_APP_BOOT_USER_SPEC\n"
            "- insert:\n"
            "    - id: user-extra\n"
            "      name: ./noop.mjs\n"
        )
    os.environ["DSH_APP_BOOT_USER_SPEC"] = "user-value"
    try:
        tree_cfg = write_tree(dir_path)
        patches = load_optional_patches(NAME, os.path.join(user_dir, PROFILE_PATCH_FILENAME))
        ctx = await boot(NAME, tree_cfg, patches)
        try:
            noop = next(entry for entry in ctx.loader.entries() if entry.options.get("id") == "noop")
            assert getattr(noop.fiber, "config", {}) == {"value": "user-value"}
            assert any(entry.options.get("id") == "user-extra" for entry in ctx.loader.entries())
        finally:
            await ctx.fiber.dispose()
    finally:
        os.environ.pop("DSH_APP_BOOT_USER_SPEC", None)


@pytest.mark.asyncio
async def test_mounts_no_patch_layer_for_an_absent_or_empty_user_layer():
    dir_path = tmp()
    ctx = await boot(NAME, write_tree(dir_path), load_optional_patches(NAME, os.path.join(tmp(), PROFILE_PATCH_FILENAME)))
    try:
        assert entry_config(ctx, "noop") == {"value": "base"}
    finally:
        await ctx.fiber.dispose()

    empty = tmp()
    with open(os.path.join(empty, PROFILE_PATCH_FILENAME), "w", encoding="utf-8") as f:
        f.write("[]\n")
    ctx_empty = await boot(NAME, write_tree(tmp()), load_optional_patches(NAME, os.path.join(empty, PROFILE_PATCH_FILENAME)))
    try:
        assert entry_config(ctx_empty, "noop") == {"value": "base"}
    finally:
        await ctx_empty.fiber.dispose()


@pytest.mark.asyncio
async def test_watches_add_failure_recovery_and_removal_through_transactional_hmr():
    dir_path = tmp()
    user_dir = tmp()
    filename = os.path.join(user_dir, PROFILE_PATCH_FILENAME)
    base_patches = [{"id": "noop", "config": {"value": "generated"}}]

    ctx = await boot(NAME, write_tree(dir_path), base_patches)
    await ctx.plugin(TimerService)
    await ctx.plugin(HmrService, {"root": [], "ignored": [], "debounce": 0})

    failures: List[Dict[str, Any]] = []
    ctx.on("hmr/config-update-failed", lambda failed_filename, error: failures.append({"filename": failed_filename, "error": error}))

    dispose = await watch_user_patches(
        ctx,
        {
            "binName": NAME,
            "filename": filename,
            "compose": lambda user_patches: base_patches + user_patches,
        },
    )

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("- id: noop\n  config:\n    value: live\n")
        await eventually(lambda: (entry_config(ctx, "noop") or {}).get("value") == "live", "user patch addition was not applied")

        with open(filename, "w", encoding="utf-8") as f:
            f.write("- id: noop\n  config:\n    fail: true\n")
        await eventually(lambda: len(failures) == 1, "failed candidate was not broadcast")
        assert failures[0]["filename"] == filename
        assert isinstance(failures[0]["error"], Exception)
        assert (entry_config(ctx, "noop") or {}).get("value") == "live"
        await asyncio.sleep(0.08)

        with open(filename, "w", encoding="utf-8") as f:
            f.write("invalid: [unclosed\n")
        await eventually(lambda: len(failures) == 2, "parse failure was not broadcast")
        assert failures[1]["filename"] == filename
        assert (entry_config(ctx, "noop") or {}).get("value") == "live"
        await asyncio.sleep(0.08)

        with open(filename, "w", encoding="utf-8") as f:
            f.write("- id: noop\n  config:\n    value: recovered\n")
        await eventually(lambda: (entry_config(ctx, "noop") or {}).get("value") == "recovered", "valid recovery was not applied")
        await asyncio.sleep(0.08)

        os.remove(filename)
        await eventually(lambda: (entry_config(ctx, "noop") or {}).get("value") == "generated", "user patch removal did not restore the app-owned patch")
        assert len(failures) == 2
        await asyncio.sleep(0.08)

        # Default compose: user layer is the whole patch list
        await dispose()
        dispose_default = await watch_user_patches(ctx, {"binName": NAME, "filename": filename})
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("- id: noop\n  config:\n    value: identity\n")
            await eventually(lambda: (entry_config(ctx, "noop") or {}).get("value") == "identity", "default-compose user patch was not applied")
        finally:
            await dispose_default()
    finally:
        await dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_fails_loud_when_the_exact_watcher_lacks_hmr_or_a_root_include():
    dir_path = tmp()
    without_hmr = await boot(NAME, write_tree(dir_path))
    with pytest.raises(RuntimeError, match="requires the Cordis HMR service"):
        await watch_user_patches(without_hmr, {"binName": NAME, "filename": os.path.join(tmp(), PROFILE_PATCH_FILENAME)})
    await without_hmr.fiber.dispose()

    without_include = Context()
    without_include.base_url = path_to_file_url(f"{tmp()}/")
    await without_include.plugin(Loader)
    await without_include.plugin(TimerService)
    await without_include.plugin(HmrService, {"root": [], "ignored": [], "debounce": 0})
    with pytest.raises(RuntimeError, match="requires the root Include entry"):
        await watch_user_patches(without_include, {"binName": NAME, "filename": os.path.join(tmp(), PROFILE_PATCH_FILENAME)})
    await without_include.fiber.dispose()


@pytest.mark.asyncio
async def test_returns_a_noop_disposer_when_the_tree_is_disposed_while_the_watcher_opens():
    dir_path = tmp()
    ctx = await boot(NAME, write_tree(dir_path))
    try:
        class InactiveHmr:
            async def register_config(self, *args, **kwargs):
                err = RuntimeError("cannot create effect on inactive context")
                setattr(err, "code", "INACTIVE_EFFECT")
                raise err

        ctx.provide("hmr", InactiveHmr())
        dispose = await watch_user_patches(ctx, {"binName": NAME, "filename": os.path.join(tmp(), PROFILE_PATCH_FILENAME)})
        res = dispose()
        if inspect.isawaitable(res):
            await res
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_propagates_registration_failures_other_than_mid_teardown():
    dir_path = tmp()
    filename = os.path.join(tmp(), PROFILE_PATCH_FILENAME)
    ctx = await boot(NAME, write_tree(dir_path))
    try:
        await ctx.plugin(TimerService)
        await ctx.plugin(HmrService, {"root": [], "ignored": [], "debounce": 0})
        dispose = await watch_user_patches(ctx, {"binName": NAME, "filename": filename})
        with pytest.raises(Exception, match="already registered"):
            await watch_user_patches(ctx, {"binName": NAME, "filename": filename})
        await dispose()
    finally:
        await ctx.fiber.dispose()
