import json
from pathlib import Path
import pytest
from dsh.boot import PluginPackages
from dsh.boot.package_resolution import PackageResolutionError
from dsh.cordis import Context
from scripts.rc022_resources_probe import fixture


@pytest.mark.asyncio
async def test_resources_do_not_evaluate_entries_and_keep_export_boundaries(tmp_path):
    table, parent = fixture(tmp_path, dict(mode='exports', value={
        '.': './explode.py', './data': './root.json', './blocked': None,
        './fallback': ['./missing.json', './root.json']}))
    library = Path(table['entries'][0]['packageDir'])
    (library/'explode.py').write_text('raise RuntimeError("must not execute")', encoding='utf-8')
    ctx = Context(); service = PluginPackages(ctx, dict(resolution=table))
    try:
        assert service.resolveResource('lib', parent) == str(library/'explode.py')
        assert service.resolveResource('lib/data', parent) == str(library/'root.json')
        for request, code in [('lib/root.json', 'ERR_PACKAGE_PATH_NOT_EXPORTED'),
                              ('lib/blocked', 'ERR_PACKAGE_PATH_NOT_EXPORTED'),
                              ('lib/fallback', 'ERR_MODULE_NOT_FOUND')]:
            with pytest.raises(PackageResolutionError) as error:
                service.resolveResource(request, parent)
            assert error.value.code == code
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_resource_lookup_reads_current_manifest_independently_of_metadata_cache(tmp_path):
    table, parent = fixture(tmp_path, dict(mode='exports', value='./root.json'))
    ctx = Context(); service = PluginPackages(ctx, dict(resolution=table))
    try:
        metadata = service.packageOf('lib', parent)
        manifest = Path(metadata['manifestPath'])
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['exports'] = './feature.json'
        manifest.write_text(json.dumps(value), encoding='utf-8')
        assert service.packageOf('lib', parent) is metadata
        assert service.resolveResource('lib', parent) == str(manifest.parent/'feature.json')
        manifest.write_text('{', encoding='utf-8')
        with pytest.raises(PackageResolutionError) as error:
            service.resolveResource('lib', parent)
        assert error.value.code == 'ERR_INVALID_PACKAGE_CONFIG'
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_import_alias_and_self_reference_use_the_callers_package_scope(tmp_path):
    table, parent = fixture(tmp_path, dict(mode='self', value={'.': './root.json'}))
    active = Path(table['profileDir'])
    manifest = active/'package.json'
    value = json.loads(manifest.read_text(encoding='utf-8'))
    value['imports'] = {'#data/*': './wild/*.json'}
    manifest.write_text(json.dumps(value), encoding='utf-8')
    ctx = Context(); service = PluginPackages(ctx, dict(resolution=table))
    try:
        assert service.resolveResource('lib', parent) == str(active/'root.json')
        assert service.resolveResource('#data/other', parent) == str(active/'wild/other.json')
        with pytest.raises(PackageResolutionError) as error:
            service.resolveResource('#data/../root', parent)
        assert error.value.code == 'ERR_INVALID_MODULE_SPECIFIER'
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_native_legacy_directory_needs_no_manifest_but_not_extension_guessing(tmp_path):
    library = tmp_path/'node_modules/lib'; library.mkdir(parents=True)
    (library/'index.json').write_text('{}', encoding='utf-8')
    (library/'data.json').write_text('{}', encoding='utf-8')
    parent = (tmp_path/'caller.py').as_uri()
    ctx = Context(); service = PluginPackages(ctx)
    try:
        assert service.packageOf('lib', parent) is None
        assert service.resolveResource('lib', parent) == str(library/'index.json')
        assert service.resolveResource('lib/data.json', parent) == str(library/'data.json')
        for request, code in [('lib/data', 'ERR_MODULE_NOT_FOUND'),
                              ('lib/a%2fb', 'ERR_INVALID_MODULE_SPECIFIER')]:
            with pytest.raises(PackageResolutionError) as error:
                service.resolveResource(request, parent)
            assert error.value.code == code
    finally: await ctx.fiber.dispose()
