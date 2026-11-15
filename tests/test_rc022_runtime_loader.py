import copy
import json
from pathlib import Path
import pytest
from dsh.boot import PluginPackages, create_runtime_resolution
from dsh.cordis import Context
from dsh.cordis.loader import Loader
from scripts import rc022_packages_probe as probe
from scripts.rc022_resolution_probe import package


def python_entries(root):
    for manifest in root.rglob('package.json'):
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['main'] = 'index.py'
        manifest.write_text(json.dumps(value), encoding='utf-8')
        (manifest.parent / 'index.py').write_text('value = '+repr(value['name'])+'\ndef apply(ctx, config): pass\n', encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected', [('active','core'),('nested','nested'),('declared-local','direct'),('linked-peer','core'),('linked-local','physical-peer'),('linked-deep','deep')])
async def test_actual_python_import_follows_the_published_package(mode, expected, tmp_path):
    table, parent = probe.fixture(tmp_path, mode)
    python_entries(tmp_path)
    ctx = Context()
    from dsh.boot.plugin_packages import _parent
    ctx.baseUrl = Path(_parent(parent)).parent.as_uri()+'/'
    loader = Loader(ctx); PluginPackages(ctx, dict(resolution=table))
    try:
        assert loader.import_plugin('core').value == expected
        package_of = ctx.get('pluginPackages').packageOf('core', parent)
        assert package_of['manifest']['name'] == expected
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_official_name_local_copy_overrides_class_table_and_hidden_private_does_not_escape(tmp_path):
    table, parent = probe.fixture(tmp_path, 'nested'); python_entries(tmp_path)
    from dsh.boot.plugin_packages import _parent
    ctx = Context(); ctx.baseUrl = Path(_parent(parent)).parent.as_uri()+'/'
    loader = Loader(ctx); PluginPackages(ctx, dict(resolution=table))
    def installation(owner, config): pass
    loader.harness_plugins['core'] = installation
    try:
        assert loader.import_plugin('core').value == 'nested'
        missing = copy.deepcopy(table); missing['entries'] = [row for row in missing['entries'] if row['scope'] == 'installation']
        ctx.get('pluginPackages').replace(missing)
        with pytest.raises(ModuleNotFoundError): loader.import_plugin('private')
        # A canonical profile never falls through to an unselected class map.
        loader.harness_plugins['private'] = installation
        with pytest.raises(ModuleNotFoundError): loader.import_plugin('private')
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_python_installation_layout_is_explicit_fresh_and_installed_copies_win(tmp_path):
    anchor = package(tmp_path / 'apps/cli', 'app', dependencies={'library':'*'})
    assert len((await create_runtime_resolution(dict(installAnchor=str(anchor),home=str(tmp_path/'home')))).entries) == 1
    options = dict(installAnchor=str(anchor),home=str(tmp_path/'home'),installationLayout=str(tmp_path))
    first = await create_runtime_resolution(options)
    package(tmp_path/'packages/runtime/library','library')
    second = await first.compute_latest_resolution()
    assert len(first.entries) == 1 and second.entries[1]['packageDir'] == str(tmp_path/'packages/runtime/library')
    package(tmp_path/'apps/cli/node_modules/library','library','2.0.0')
    third = await second.compute_latest_resolution()
    assert third.entries[1]['version'] == '2.0.0'
    assert not (tmp_path/'home').exists()


@pytest.mark.asyncio
async def test_canonical_launcher_publishes_runtime_without_healing_fallback(tmp_path, monkeypatch):
    import dsh.boot.profile_boot as launcher
    from dsh.boot.profile import init_profile
    home = tmp_path/'explicit-home'; active = home/'profiles/test'
    init_profile(str(active), [])
    monkeypatch.setenv('DSH_HOME',str(tmp_path/'ambient-home'))
    result = await launcher.run_profile(dict(profile='test',dsh_home=str(home),wait_for_exit=False))
    try:
        ctx = result['ctx']; service = ctx.get('pluginPackages')
        assert service is not None and len(service.resolution.entries) > 100
        assert service.resolution.profileDir == str(active)
        assert ctx.get('loader').installation_module_roots == []
        assert not (home/'profiles/node_modules').exists()
        assert not (active/'.dsh-module-fallback').exists()
        assert not (tmp_path/'ambient-home/profiles/node_modules').exists()
    finally:
        result['shutdown'].shutdown(0); await result['shutdown'].wait()
