import asyncio
from pathlib import Path
import pytest
from dsh.boot import PluginPackages
from dsh.boot.package_resolution import PackageResolutionError
from dsh.cordis import Context
from dsh.cordis.loader import Loader
from scripts import rc022_resource_consumers_probe as probe
from scripts.rc022_resources_probe import fixture


def test_actual_import_and_preflight_resource_journeys(tmp_path):
    probe.prepare(tmp_path)
    rows = asyncio.run(probe.native())
    assert len(rows) == 22
    by_case = {}
    for row in rows: by_case.setdefault(row['case'], []).append(row)
    assert by_case[0][0]['value'] == 'lib/node'
    assert by_case[3][0]['code'] == 'ERR_MODULE_NOT_FOUND'
    assert by_case[7][0]['value'] == 'active/root'
    assert by_case[8][0]['value'] == 'lib/root'
    assert by_case[9][0]['value'] == 'active/specific/item'
    assert by_case[10][0]['value'] == 'active/node'
    assert all(row['disabled'] for row in by_case[13])


@pytest.mark.asyncio
async def test_installation_class_adapter_cannot_bypass_a_blocked_export(tmp_path):
    table, parent = fixture(tmp_path, dict(mode='exports', value={'.': None}))
    ctx = Context(); ctx.baseUrl = Path(table['profileDir']).as_uri()+'/'
    loader = Loader(ctx); PluginPackages(ctx, dict(resolution=table))
    loader.harness_plugins['lib'] = lambda owner, config: None
    try:
        with pytest.raises(PackageResolutionError) as error: loader.import_plugin('lib')
        assert error.value.code == 'ERR_PACKAGE_PATH_NOT_EXPORTED'
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_python_export_suffix_is_relative_to_tree_and_cannot_escape_to_registry(tmp_path):
    table, parent = fixture(tmp_path, dict(mode='exports', value='./root.json'))
    active = Path(table['profileDir'])
    (active/'entry.py').write_text('class Export:\n    value = 42\n',encoding='utf-8')
    ctx = Context(); ctx.baseUrl = active.as_uri()+'/'
    loader = Loader(ctx); PluginPackages(ctx, dict(resolution=table))
    loader.registry_map['./missing.py:Export'] = object()
    try:
        assert loader.import_plugin('./entry.py:Export').value == 42
        with pytest.raises(ModuleNotFoundError): loader.import_plugin('./missing.py:Export')
    finally: await ctx.fiber.dispose()
