"""
1:1 parity test suite porting reference/packages/boot/app-boot/tests/config-reload.spec.ts
Tests transactional config replacement through booted Include and Loader tree.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import builtins
import inspect
import os
import shutil
import tempfile
from typing import Any, Dict, NamedTuple, Optional

import pytest

from dsh.boot.app_boot import boot
from dsh.cordis.context import Context
from dsh.cordis.include import Include
from dsh.cordis.loader import Entry

NAME = "dsh-test-bin"
NOOP_PLUGIN = 'export const name = "noop"\nexport function apply() {}\n'


class TreeFixture(NamedTuple):
    ctx: Context
    dir: str
    include: Include


def plugin(name: str, body: str = "") -> str:
    return f"export default function {name}(_ctx, config = {{}}) {{ {body} }}\n"


async def boot_tree(config_body: str, files: Optional[Dict[str, str]] = None) -> TreeFixture:
    tmp_dir = tempfile.mkdtemp(prefix="dsh-config-reload-")
    with open(os.path.join(tmp_dir, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write(NOOP_PLUGIN)
    if files:
        for fname, fcontent in files.items():
            fpath = os.path.join(tmp_dir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(fcontent)
    config_path = os.path.join(tmp_dir, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_body)

    ctx = await boot(NAME, config_path)
    include_entry = None
    for candidate in ctx.loader.entries():
        if getattr(candidate, "subtree", None) is not None:
            include_entry = candidate
            break
    if include_entry is None:
        raise RuntimeError("booted tree has no include entry")
    return TreeFixture(ctx=ctx, dir=tmp_dir, include=include_entry.subtree)


def entry_config(ctx: Context, entry_id: str) -> Any:
    for entry in ctx.loader.entries():
        if entry.options.get("id") == entry_id:
            return entry.options.get("config")
    return None


def entry_by_id(ctx: Context, entry_id: str) -> Entry:
    for entry in ctx.loader.entries():
        if entry.options.get("id") == entry_id:
            return entry
    raise RuntimeError(f"missing loader entry {entry_id}")


async def expect_update_failure(task: Any, stage: str) -> None:
    try:
        if inspect.isawaitable(task):
            await task
    except Exception as error:
        err_msg = str(error)
        assert f"failed to {stage} loader entry" in err_msg, f"Expected error to contain 'failed to {stage} loader entry', got: {err_msg}"
        return
    raise AssertionError(f"expected loader update to fail during {stage}")


# --- Include refresh with an invalid file ---

@pytest.mark.asyncio
async def test_include_refresh_with_an_invalid_file_rejects_and_retains_good_tree():
    fixture = await boot_tree("- id: noop\n  name: ./noop.mjs\n  config:\n    value: 1\n")
    ctx, dir_path, include = fixture.ctx, fixture.dir, fixture.include
    try:
        assert entry_config(ctx, "noop") == {"value": 1}

        config_path = os.path.join(dir_path, "cordis.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("invalid: [unclosed\n")
        with pytest.raises(Exception, match="failed to parse config file"):
            await include.refresh()
        assert entry_config(ctx, "noop") == {"value": 1}

        # An empty file parses to None without a YAML error; treated like parse failure
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("")
        with pytest.raises(Exception, match="failed to validate config file"):
            await include.refresh()
        assert entry_config(ctx, "noop") == {"value": 1}

        with open(config_path, "w", encoding="utf-8") as f:
            f.write("- id: noop\n  name: ./noop.mjs\n  config:\n    value: 2\n")
        await include.refresh()
        await ctx.loader.await_()
        assert entry_config(ctx, "noop") == {"value": 2}
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


# --- Loader entry replacement ---

@pytest.mark.asyncio
async def test_imports_a_changed_name_before_replacing_the_running_plugin():
    fixture = await boot_tree(
        "- id: target\n  name: ./old.mjs\n",
        {
            "old.mjs": plugin("oldPlugin"),
            "new.mjs": plugin("newPlugin"),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        entry = entry_by_id(ctx, "target")
        res = entry.update({"name": "./new.mjs"})
        if inspect.isawaitable(res):
            await res
        assert entry.options.get("name") == "./new.mjs"
        assert any(opt.get("id") == "target" for opt in entry.parent.data)
        assert getattr(entry.fiber.runtime.callback, "name", None) == "newPlugin"
        assert entry.options.get("disabled") is None or entry.options.get("disabled") is False
        if entry.fiber and hasattr(entry.fiber, "await_settled"):
            await entry.fiber.await_settled()
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_retains_the_running_plugin_when_the_replacement_cannot_be_imported():
    fixture = await boot_tree(
        "- id: target\n  name: ./old.mjs\n",
        {
            "old.mjs": plugin("oldPlugin"),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        entry = entry_by_id(ctx, "target")
        fiber = entry.fiber
        await expect_update_failure(entry.update({"name": "./missing.mjs"}), "import")
        assert entry.options.get("name") == "./old.mjs"
        assert entry.fiber is fiber
        if fiber and hasattr(fiber, "await_settled"):
            await fiber.await_settled()
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_restores_the_previous_plugin_after_replacement_application_fails():
    fixture = await boot_tree(
        "- id: target\n  name: ./old.mjs\n",
        {
            "old.mjs": plugin("oldPlugin"),
            "bad.mjs": plugin("badPlugin", 'throw new Error("candidate apply failed")'),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        entry = entry_by_id(ctx, "target")
        previous = entry.fiber
        await expect_update_failure(entry.update({"name": "./bad.mjs"}), "apply")
        assert entry.options.get("name") == "./old.mjs"
        assert entry.fiber is not previous
        assert getattr(entry.fiber.runtime.callback, "name", None) == "oldPlugin"
        assert entry.options.get("disabled") is None or entry.options.get("disabled") is False
        if entry.fiber and hasattr(entry.fiber, "await_settled"):
            await entry.fiber.await_settled()
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_restores_the_previous_config_when_an_in_place_restart_fails():
    fixture = await boot_tree(
        "- id: target\n  name: ./configurable.mjs\n  config:\n    fail: false\n",
        {
            "configurable.mjs": plugin("configurablePlugin", 'if (config.fail) throw new Error("candidate config failed")'),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        entry = entry_by_id(ctx, "target")
        fiber = entry.fiber
        await expect_update_failure(entry.update({"config": {"fail": True}}), "apply")
        assert entry.options.get("config") == {"fail": False}
        assert entry.fiber is fiber
        if fiber and hasattr(fiber, "await_settled"):
            await fiber.await_settled()
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_does_not_persist_a_failed_direct_fiber_update():
    fixture = await boot_tree(
        "- id: target\n  name: ./configurable.mjs\n  config:\n    fail: false\n",
        {
            "configurable.mjs": plugin("configurablePlugin", 'if (config.fail) throw new Error("candidate config failed")'),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        entry = entry_by_id(ctx, "target")
        fiber = entry.fiber
        assert fiber is not None
        with pytest.raises(Exception, match="candidate config failed"):
            await fiber.update({"fail": True})
        assert entry.options.get("config") == {"fail": False}
        assert any(opt.get("id") == "target" for opt in entry.parent.data)
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


# --- Loader tree replacement ---

@pytest.mark.asyncio
async def test_rolls_back_earlier_updates_and_additions_when_a_later_entry_fails():
    fixture = await boot_tree(
        "- id: existing\n  name: ./configurable.mjs\n  config:\n    value: old\n",
        {
            "configurable.mjs": plugin("configurablePlugin"),
            "bad.mjs": plugin("badPlugin", 'throw new Error("candidate apply failed")'),
        },
    )
    ctx, dir_path, include = fixture.ctx, fixture.dir, fixture.include
    try:
        config_path = os.path.join(dir_path, "cordis.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "- id: existing\n"
                "  name: ./configurable.mjs\n"
                "  config:\n"
                "    value: candidate\n"
                "- id: added\n"
                "  name: ./noop.mjs\n"
                "- id: bad\n"
                "  name: ./bad.mjs\n"
            )
        with pytest.raises(Exception, match="failed to apply loader entry bad"):
            await include.refresh()

        assert entry_config(ctx, "existing") == {"value": "old"}
        assert not any(entry.options.get("id") == "added" for entry in ctx.loader.entries())
        assert not any(entry.options.get("id") == "bad" for entry in ctx.loader.entries())

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "- id: existing\n"
                "  name: ./configurable.mjs\n"
                "  config:\n"
                "    value: committed\n"
                "- id: added\n"
                "  name: ./noop.mjs\n"
            )
        await include.refresh()
        assert entry_config(ctx, "existing") == {"value": "committed"}
        assert entry_by_id(ctx, "added").fiber is not None
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_stops_and_restores_descendants_when_an_ancestor_group_is_disabled_and_reenabled():
    fixture = await boot_tree("- id: noop\n  name: ./noop.mjs\n")
    ctx, dir_path, include = fixture.ctx, fixture.dir, fixture.include
    try:
        def group_config(disabled: bool) -> str:
            return (
                "- id: parent\n"
                "  name: cordis:group\n"
                "  group: true\n"
                f"  disabled: {'true' if disabled else 'false'}\n"
                "  config:\n"
                "    - id: child\n"
                "      name: ./noop.mjs\n"
            )

        config_path = os.path.join(dir_path, "cordis.yml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(group_config(False))
        await include.refresh()
        assert entry_by_id(ctx, "child").fiber is not None

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(group_config(True))
        await include.refresh()
        assert entry_by_id(ctx, "child").fiber is None

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(group_config(False))
        await include.refresh()
        assert entry_by_id(ctx, "child").fiber is not None
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_restores_a_programmatic_entry_move_when_its_update_fails():
    fixture = await boot_tree(
        "- id: noop\n  name: ./noop.mjs\n",
        {
            "movable.mjs": plugin("movablePlugin", 'if (config.fail) throw new Error("candidate config failed")'),
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        group_id = await ctx.loader.create({"name": "cordis:group", "group": True, "config": []})
        target_id = await ctx.loader.create({"name": "./movable.mjs", "config": {"fail": False}})
        target = entry_by_id(ctx, target_id)
        source = target.parent
        source_index = source.data.index(target.options)
        group_entry = entry_by_id(ctx, group_id)
        destination = group_entry.subgroup
        assert destination is not None, "created loader group has no subgroup"

        await expect_update_failure(
            ctx.loader.update(target_id, {"config": {"fail": True}}, group_id),
            "apply",
        )

        assert target.parent == source
        assert source.data.index(target.options) == source_index
        assert target.options not in destination.data
        assert target.options.get("config") == {"fail": False}
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)


# --- Include refresh with overlay patches ---

@pytest.mark.asyncio
async def test_reapplies_entry_patches_and_inserted_entries_on_every_reread():
    tmp_dir = tempfile.mkdtemp(prefix="dsh-config-reload-overlay-")
    try:
        with open(os.path.join(tmp_dir, "noop.mjs"), "w", encoding="utf-8") as f:
            f.write(NOOP_PLUGIN)
        with open(os.path.join(tmp_dir, "base.yml"), "w", encoding="utf-8") as f:
            f.write("- id: noop\n  name: ./noop.mjs\n  config:\n    value: base\n")
        with open(os.path.join(tmp_dir, "cordis.yml"), "w", encoding="utf-8") as f:
            f.write(
                "- id: base\n"
                "  name: 'cordis:include'\n"
                "  config:\n"
                "    path: ./base.yml\n"
                "    patches:\n"
                "      - id: noop\n"
                "        name: ./noop.mjs\n"
                "        config:\n"
                "          value: patched\n"
                "      - insert:\n"
                "          - id: extra\n"
                "            name: ./noop.mjs\n"
            )

        ctx = await boot(NAME, os.path.join(tmp_dir, "cordis.yml"))
        try:
            include_entry = None
            for candidate in ctx.loader.entries():
                if candidate.options.get("id") == "base":
                    include_entry = candidate
                    break
            assert include_entry is not None and getattr(include_entry, "subtree", None) is not None
            include: Include = include_entry.subtree

            assert entry_config(ctx, "noop") == {"value": "patched"}
            assert entry_config(ctx, "extra") is None
            assert any(candidate.options.get("id") == "extra" for candidate in ctx.loader.entries())

            with open(os.path.join(tmp_dir, "base.yml"), "w", encoding="utf-8") as f:
                f.write("- id: noop\n  name: ./noop.mjs\n  config:\n    value: edited\n")
            await include.refresh()
            await ctx.loader.await_()
            assert entry_config(ctx, "noop") == {"value": "patched"}
            assert any(candidate.options.get("id") == "extra" for candidate in ctx.loader.entries())

            # Hot-update of include entry's own config
            res = include_entry.update({"config": {"path": "./base.yml", "patches": [{"id": "noop", "name": "./noop.mjs", "config": {"value": "patched-v2"}}]}})
            if inspect.isawaitable(res):
                await res
            await ctx.loader.await_()
            assert entry_config(ctx, "noop") == {"value": "patched-v2"}
            assert not any(candidate.options.get("id") == "extra" for candidate in ctx.loader.entries())

            with open(os.path.join(tmp_dir, "base.yml"), "w", encoding="utf-8") as f:
                f.write("- id: noop\n  name: ./noop.mjs\n  config:\n    value: edited-2\n")
            await include.refresh()
            await ctx.loader.await_()
            assert entry_config(ctx, "noop") == {"value": "patched-v2"}

            # Omitting patch list removes overlay
            res = include_entry.update({"config": {"path": "./base.yml"}})
            if inspect.isawaitable(res):
                await res
            await ctx.loader.await_()
            assert entry_config(ctx, "noop") == {"value": "edited-2"}
        finally:
            await ctx.fiber.dispose()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Include patches layered over one base ---

@pytest.mark.asyncio
async def test_lets_a_later_patch_configure_or_disable_a_row_an_earlier_patch_inserted():
    tmp_dir = tempfile.mkdtemp(prefix="dsh-config-layered-")
    try:
        with open(os.path.join(tmp_dir, "noop.mjs"), "w", encoding="utf-8") as f:
            f.write(NOOP_PLUGIN)
        with open(os.path.join(tmp_dir, "base.yml"), "w", encoding="utf-8") as f:
            f.write("- id: shared\n  name: ./noop.mjs\n  config:\n    value: base\n")
        with open(os.path.join(tmp_dir, "cordis.yml"), "w", encoding="utf-8") as f:
            f.write(
                "- id: base\n"
                "  name: 'cordis:include'\n"
                "  config:\n"
                "    path: ./base.yml\n"
                "    patches:\n"
                "      - id: shared\n"
                "        config:\n"
                "          value: bundle\n"
                "      - insert:\n"
                "          - id: bundle-kept\n"
                "            name: ./noop.mjs\n"
                "            config:\n"
                "              value: bundle-default\n"
                "          - id: bundle-dropped\n"
                "            name: ./noop.mjs\n"
                "      - id: bundle-kept\n"
                "        config:\n"
                "          value: user\n"
                "      - id: bundle-dropped\n"
                "        disabled: true\n"
            )

        ctx = await boot(NAME, os.path.join(tmp_dir, "cordis.yml"))
        try:
            assert entry_config(ctx, "shared") == {"value": "bundle"}
            assert entry_config(ctx, "bundle-kept") == {"value": "user"}
            dropped = next((entry for entry in ctx.loader.entries() if entry.options.get("id") == "bundle-dropped"), None)
            assert dropped is not None
            assert dropped.options.get("disabled") is True
            assert dropped.fiber is None
        finally:
            await ctx.fiber.dispose()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Shipped builtins: isolate realm ---

@pytest.mark.asyncio
async def test_lets_a_booted_composition_share_one_isolate_realm_across_a_group_of_rows():
    provider_code = (
        'export const name = "provider"\n'
        'export function apply(ctx) { ctx.effect(() => ctx.reflect.provide("demoRealmSvc", { tag: "realm" })) }\n'
    )
    consumer_code = (
        'export const name = "consumer"\n'
        'export const inject = ["demoRealmSvc"]\n'
        'export function apply(ctx) { globalThis.__REALM_SEEN__ = ctx.get("demoRealmSvc").tag }\n'
    )
    fixture = await boot_tree(
        "- id: realm\n"
        "  name: cordis:group\n"
        "  isolate:\n"
        "    demoRealmSvc: true\n"
        "  config:\n"
        "    - id: provider\n"
        "      name: ./provider.mjs\n"
        "    - id: consumer\n"
        "      name: ./consumer.mjs\n",
        {
            "provider.mjs": provider_code,
            "consumer.mjs": consumer_code,
        },
    )
    ctx, dir_path = fixture.ctx, fixture.dir
    try:
        assert getattr(builtins, "__REALM_SEEN__", None) == "realm"
        root_key = ctx.root[Context.isolate].demoRealmSvc
        assert root_key is not None
        assert ctx.reflect.store[root_key] is None
    finally:
        if hasattr(builtins, "__REALM_SEEN__"):
            delattr(builtins, "__REALM_SEEN__")
        await ctx.fiber.dispose()
        shutil.rmtree(dir_path, ignore_errors=True)
