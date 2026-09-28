import json
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.abort import AbortController
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.llm.plugin_package_inventory import PluginPackageInventoryDeepSeek
from dsh.llm.plugin_package_inventory import PackageIdentityResolver


def package(root, name, version):
    directory = root / "node_modules" / name
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps({"name": name, "version": version, "main": "index.py"}), encoding="utf-8")
    (directory / "index.py").write_text("def apply(ctx, config=None):\n    pass\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_inventory_reads_active_loader_provenance_and_releases_field(tmp_path):
    package(tmp_path, "@fixture/z", "2.0.0")
    package(tmp_path, "@fixture/a", "1.0.0")
    package(tmp_path, "@fixture/unused", "3.0.0")
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})
    ctx.set_service("agents", SimpleNamespace(get=lambda _: None))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    install_harness_plugin_classes(loader)
    rows = [{"id": "z", "name": "@fixture/z"}, {"id": "a", "name": "@fixture/a"},
            {"id": "duplicate", "name": "@fixture/a"}, {"id": "unused", "name": "@fixture/unused", "disabled": True}]
    await loader.root.update(rows)
    mounted = await ctx.plugin(PluginPackageInventoryDeepSeek)
    async def packages():
        prepared = await ctx.get("deepseekLlmApiExtensions").prepare({"body": {}, "signal": AbortController().signal})
        return prepared.fields["dsh_plugin_packages"]["packages"]
    try:
        assert await packages() == [{"name": "@fixture/a", "version": "1.0.0"}, {"name": "@fixture/z", "version": "2.0.0"}]
        await loader.update("z", {"disabled": True})
        assert await packages() == [{"name": "@fixture/a", "version": "1.0.0"}]
        await mounted.dispose()
        assert (await ctx.get("deepseekLlmApiExtensions").prepare({"body": {}, "signal": AbortController().signal})).fields == {}
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_inventory_installation_identity_is_not_dependency_inventory(tmp_path):
    ctx = Context()
    loader = Loader(ctx, {"baseUrl": str(tmp_path)})
    ctx.set_service("agents", SimpleNamespace(get=lambda _: None))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    install_harness_plugin_classes(loader)
    await loader.root.update([{"id": "inventory", "name": "@deepseek-ai/dsh-plugin-package-inventory-deepseek"}])
    try:
        fields = (await ctx.get("deepseekLlmApiExtensions").prepare({"body": {}, "signal": AbortController().signal})).fields
        packages = fields["dsh_plugin_packages"]["packages"]
        assert len(packages) == 1 and packages[0]["name"] == "@deepseek-ai/dsh-plugin-package-inventory-deepseek"
        assert packages[0]["version"]
    finally:
        await ctx.fiber.dispose()


def test_manifest_identity_cache_and_loose_module_validation(tmp_path):
    tree = SimpleNamespace(ctx=SimpleNamespace(baseUrl=str(tmp_path)))
    entry = SimpleNamespace(parent=SimpleNamespace(tree=tree), options={"name": "./plugin.py"})
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"name": "local", "version": "1"}), encoding="utf-8")
    resolver = PackageIdentityResolver(str(tmp_path), SimpleNamespace())
    assert resolver.resolve(entry) == {"name": "local", "version": "1"}
    manifest.write_text(json.dumps({"name": "local", "version": "2"}), encoding="utf-8")
    assert resolver.resolve(entry)["version"] == "1"
    manifest.write_text(json.dumps({"version": "2"}), encoding="utf-8")
    assert PackageIdentityResolver(str(tmp_path), SimpleNamespace()).resolve(entry) is None
    manifest.write_text(json.dumps({"name": "local"}), encoding="utf-8")
    with pytest.raises(ValueError, match="name and version"):
        PackageIdentityResolver(str(tmp_path), SimpleNamespace()).resolve(entry)


@pytest.mark.asyncio
async def test_disabled_inventory_has_no_request_contribution(tmp_path):
    ctx = Context()
    Loader(ctx, {"baseUrl": str(tmp_path)})
    ctx.set_service("agents", SimpleNamespace(get=lambda _: None))
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    await ctx.plugin(PluginPackageInventoryDeepSeek, {"enabled": False})
    try:
        result = await ctx.get("deepseekLlmApiExtensions").prepare({"body": {}, "signal": AbortController().signal})
        assert result.fields == {}
    finally:
        await ctx.fiber.dispose()
