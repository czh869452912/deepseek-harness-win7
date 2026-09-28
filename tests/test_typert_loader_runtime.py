import asyncio
import json
from pathlib import Path

import pytest

from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.fiber import FiberState
from dsh.typert.artifact import ArtifactParser, UNDEFINED, read_generated_artifact
from dsh.typert.loader import TypertLoader, validate_manifest
from dsh.typert.registry import TypertRegistry


def package(root, name, broken=False):
    directory = root / "node_modules" / name
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps({"name": name, "main": "index.py", "exports": {".": "./index.py", "./typert": "./typert.js"}}), encoding="utf-8")
    (directory / "index.py").write_text("def apply(ctx, config=None):\n    pass\n", encoding="utf-8")
    source = """import { z } from 'zod'
const value = z.object({text: z.string(), count: z.number().optional()})
export const TYPERT = {package: PACKAGE, face: 'host', schemas: [{name: 'Value', schema: value}],
  model: {services: [], events: [], objects: []}, invocations: []}
""".replace("PACKAGE", json.dumps("wrong" if broken else name))
    (directory / "typert.js").write_text(source, encoding="utf-8")
    return directory


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_real_loader_duplicate_rows_unload_and_cached_artifact(tmp_path):
    directory = package(tmp_path, "@fixture/a")
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})
    await ctx.plugin(TypertRegistry)
    await loader.root.update([{"id": "one", "name": "@fixture/a"}, {"id": "two", "name": "@fixture/a"}])
    fiber = await ctx.plugin(TypertLoader)
    registry = ctx.get("typert")
    try:
        assert fiber.state == FiberState.ACTIVE
        assert registry.resolve("@fixture/a#Value")["schema"].parse({"text": "yes", "other": 1}) == {"text": "yes"}
        with pytest.raises(ValueError):
            registry.resolve("@fixture/a#Value")["schema"].parse({"text": 1})
        await loader.update("one", {"disabled": True})
        await settle()
        assert registry.getPackage("@fixture/a") is not None
        await loader.update("two", {"disabled": True})
        await settle()
        assert registry.getPackage("@fixture/a") is None
        (directory / "typert.js").write_text("not executable", encoding="utf-8")
        await loader.update("one", {"disabled": False})
        await settle()
        assert registry.getPackage("@fixture/a") is not None
        await fiber.dispose()
        assert registry.getPackage("@fixture/a") is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_initial_broken_artifact_fails_activation_and_withdraws_other_contributions(tmp_path):
    package(tmp_path, "@fixture/good")
    package(tmp_path, "@fixture/bad", broken=True)
    ctx = Context()
    Loader(ctx, {"baseUrl": str(tmp_path)})
    await ctx.plugin(TypertRegistry)
    try:
        with pytest.raises(ValueError, match="contributor.*failed"):
            await ctx.plugin(TypertLoader, config={"packages": ["@fixture/good", "@fixture/bad"]})
        await settle()
        assert ctx.get("typert").listPackages() == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_installation_artifact_supplies_real_llm_strict_invocations(tmp_path):
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})
    install_harness_plugin_classes(loader)
    await ctx.plugin(TypertRegistry)
    await loader.root.update([{"id": "llm", "name": "@deepseek-ai/dsh-llm"}])
    try:
        fiber = await ctx.plugin(TypertLoader)
        assert fiber.state == FiberState.ACTIVE
        row = ctx.get("typert").local.get("llm/discoverModels")
        assert row["parameters"][0]["codec"]["schema"].parse("deepseek") == "deepseek"
        with pytest.raises(ValueError):
            row["parameters"][0]["codec"]["schema"].parse(42)
        assert len(ctx.get("typert").local.list()) == 3
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_steady_state_broken_package_is_contained_and_local_package_wins(tmp_path, caplog):
    package(tmp_path, "@deepseek-ai/dsh-llm")
    package(tmp_path, "@fixture/bad", broken=True)
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})
    install_harness_plugin_classes(loader)
    await ctx.plugin(TypertRegistry)
    fiber = await ctx.plugin(TypertLoader)
    try:
        await loader.root.update([{"id": "local", "name": "@deepseek-ai/dsh-llm"}, {"id": "bad", "name": "@fixture/bad"}])
        await settle()
        assert fiber.state == FiberState.ACTIVE
        assert ctx.get("typert").get("@deepseek-ai/dsh-llm#Value") is not None
        assert ctx.get("typert").local.get("llm/discoverModels") is None
        assert ctx.get("typert").getPackage("@fixture/bad") is None
        assert "owning package" in caplog.text
    finally:
        await ctx.fiber.dispose()


def test_all_shipped_artifacts_are_executable_and_recursive_json_codec_rejects_non_json():
    paths = list(Path("packages").rglob("typert.host.js"))
    assert len(paths) == 13
    manifests = {}
    for path in paths:
        manifest = read_generated_artifact(path)
        manifests[manifest["package"]] = validate_manifest(manifest["package"], manifest)
    invocation = next(row for row in manifests["@deepseek-ai/dsh-api-settings-controller"]["invocations"] if row["method"] == "replace")
    schema = invocation["parameters"][1]["codec"]["schema"]
    assert schema.parse({"x": [1, None, {"a": False}]}) == {"x": [1, None, {"a": False}]}
    with pytest.raises(ValueError):
        schema.parse({"x": object()})
    assert "$defs" in schema.to_json_schema()


def test_generated_grammar_rejects_executable_code_and_preserves_undefined():
    with pytest.raises(ValueError):
        ArtifactParser("import { z } from 'zod'; process.exit(0)").parse()
    manifest = ArtifactParser("import { z } from 'zod'; export const TYPERT = {schema: z.union([z.undefined(), z.string()])}").parse()
    assert manifest["schema"].parse(UNDEFINED) is UNDEFINED
    with pytest.raises(ValueError):
        manifest["schema"].parse(None)
