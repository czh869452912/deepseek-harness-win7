"""Current booted Include recovery/overlays from the pinned config-reload.spec.ts.

The upstream target publishes raw options and applies best-effort edits. Historical
transaction rollback assertions do not describe this contract.
"""
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



@pytest.mark.asyncio
async def test_invalid_include_keeps_last_good_tree_then_accepts_a_valid_edit():
    fixture = await boot_tree("- id: noop\n  name: ./noop.mjs\n  config: { value: 1 }\n")
    ctx, directory, include = fixture
    try:
        filename = os.path.join(directory, 'cordis.yml')
        for invalid in ('invalid: [unclosed\n', ''):
            with open(filename, 'w', encoding='utf-8') as stream:
                stream.write(invalid)
            assert await include.refresh() is None
            assert entry_config(ctx, 'noop') == {'value': 1}
        with open(filename, 'w', encoding='utf-8') as stream:
            stream.write('- id: noop\n  name: ./noop.mjs\n  config: { value: 2 }\n')
        await include.refresh()
        await ctx.loader.await_()
        assert entry_config(ctx, 'noop') == {'value': 2}
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory)


@pytest.mark.asyncio
async def test_missing_include_writes_and_activates_initial_entries():
    fixture = await boot_tree(
        "- id: initialized\n  name: cordis:include\n  config:\n"
        "    path: ./created.yml\n    initial:\n      - id: noop\n"
        "        name: ./noop.mjs\n        config: { value: initial }\n")
    ctx, directory, _ = fixture
    try:
        assert entry_config(ctx, 'noop') == {'value': 'initial'}
        with open(os.path.join(directory, 'created.yml'), encoding='utf-8') as stream:
            assert 'id: noop' in stream.read()
        assert entry_by_id(ctx, 'noop').fiber.state == 2
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected_state', [
    ('import', None), ('sync apply', 3), ('async apply', 3), ('dependency', 0)])
async def test_required_id_reload_failure_keeps_siblings_and_recovers(kind, expected_state):
    sources = {
        'sync apply': 'def apply(ctx, config):\n    if config["fail"]: raise RuntimeError("reload sync failure")\n',
        'async apply': 'import asyncio\nasync def apply(ctx, config):\n    await asyncio.sleep(0)\n    if config["fail"]: raise RuntimeError("reload async failure")\n',
        'dependency': 'inject = ["reloadMissing"]\ndef apply(ctx, config): pass\n',
    }
    files = {'provider.py': 'def apply(ctx, config): ctx.provide("reloadMissing", True)\n'}
    if kind != 'import':
        files['failure.py'] = sources[kind]
    base = '- id: good\n  name: ./noop.mjs\n'
    fixture = await boot_tree(base, files)
    ctx, directory, include = fixture
    try:
        good = entry_by_id(ctx, 'good').fiber
        filename = os.path.join(directory, 'cordis.yml')
        with open(filename, 'w', encoding='utf-8') as stream:
            stream.write(base + '- id: webserver\n  name: ./failure.py\n  config: { fail: true }\n')
        await include.refresh()
        await ctx.loader.await_()
        failed = entry_by_id(ctx, 'webserver')
        assert (failed.fiber.state if failed.fiber is not None else None) == expected_state
        assert good.state == ctx.fiber.state == 2
        replacement = 'noop.mjs' if kind == 'import' else 'failure.py'
        provider = '- id: provider\n  name: ./provider.py\n' if kind == 'dependency' else ''
        with open(filename, 'w', encoding='utf-8') as stream:
            stream.write(base + '- id: webserver\n  name: ./' + replacement + '\n  config: { fail: false }\n' + provider)
        await include.refresh()
        await ctx.loader.await_()
        assert entry_by_id(ctx, 'webserver').fiber.state == 2
        assert entry_by_id(ctx, 'good').fiber is good
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory)


@pytest.mark.asyncio
async def test_schema_rejection_keeps_effective_config_and_retries_valid_edit():
    def composition(value):
        import json
        return '- id: webserver\n  name: ./schema.py\n  config: { value: ' + json.dumps(value) + ' }\n'
    fixture = await boot_tree(composition(1), {'schema.py':
        'from dsh.cordis.schema import Schema\n'
        'Config = Schema.object({"value": Schema.number().required()})\n'
        'def apply(ctx, config): ctx.provide("validatedValue", config["value"])\n'})
    ctx, directory, include = fixture
    try:
        entry = entry_by_id(ctx, 'webserver')
        filename = os.path.join(directory, 'cordis.yml')
        with open(filename, 'w', encoding='utf-8') as stream:
            stream.write(composition('invalid'))
        await include.refresh()
        await ctx.loader.await_()
        assert entry.options['config'] == {'value': 'invalid'}
        assert entry.fiber.effectiveConfig == {'value': 1}
        assert ctx.get('validatedValue') == 1
        with open(filename, 'w', encoding='utf-8') as stream:
            stream.write(composition(2))
        await include.refresh()
        await ctx.loader.await_()
        assert entry.fiber.effectiveConfig == {'value': 2}
        assert ctx.get('validatedValue') == 2
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory)


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
