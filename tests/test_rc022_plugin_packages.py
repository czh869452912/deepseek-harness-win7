import asyncio
import copy
from pathlib import Path
import pytest
from dsh.cordis import Context
from dsh.boot.plugin_packages import PluginPackages, ResolutionRouter, ResolutionRestartRequired
from dsh.boot.runtime_resolution import create_runtime_resolution
from scripts import rc022_packages_probe as probe
from scripts import rc022_resolution_probe as resolution_probe


def test_real_routes_caches_and_publication(tmp_path):
    probe.OUTPUT = tmp_path
    rows = asyncio.run(probe.native())
    assert len(rows) == 46
    modes = {row['mode']: row for row in rows if 'mode' in row}
    assert modes['nested']['packages']['core']['name'] == 'nested'
    assert modes['local-empty']['packages']['core'] is None
    assert modes['sibling']['packages']['private'] is None
    assert modes['active']['packages']['private']['name'] == 'private'
    assert modes['linked-peer']['packages']['core']['name'] == 'core'
    assert modes['linked-local']['packages']['core']['name'] == 'physical-peer'
    assert modes['linked-deep']['packages']['core']['name'] == 'deep'
    assert modes['cache']['cached']['name'] == 'core'
    assert modes['cache']['replacement']['name'] == 'edited'
    assert modes['cache-absence']['cached'] is None
    assert modes['cache-absence']['replacement']['name'] == 'edited'
    for name in ('installation-version', 'profile-move', 'local-add'):
        assert modes['replace-' + name]['restart'] and modes['replace-' + name]['same_cache']
    assert modes['replace-profile-version']['published']


@pytest.mark.asyncio
async def test_service_recompute_is_atomic_and_owned(tmp_path):
    options = resolution_probe.fixture(tmp_path, 'profile')
    table = await create_runtime_resolution(options)
    ctx = Context(); service = PluginPackages(ctx, dict(resolution=table))
    assert ctx.get('pluginPackages') is not None
    parent = (Path(options['profile']['dir']) / 'caller.mjs').as_uri()
    first = service.packageOf('private', parent)
    manifest = Path(options['profile']['dir']) / 'package.json'
    text = manifest.read_text(encoding='utf-8'); manifest.write_text('{', encoding='utf-8')
    with pytest.raises(RuntimeError):
        await service.refresh()
    assert service.resolution is table and service.packageOf('private', parent) is first
    manifest.write_text(text, encoding='utf-8')
    await service.refresh()
    assert service.resolution is not table and service.packageOf('private', parent) is not first
    await ctx.fiber.dispose()
    assert ctx.get('pluginPackages') is None


@pytest.mark.asyncio
async def test_absent_and_plain_data_cannot_refresh(tmp_path):
    table, _ = probe.fixture(tmp_path, 'active')
    for config in ({}, dict(resolution=table)):
        ctx = Context(); service = PluginPackages(ctx, config)
        with pytest.raises(RuntimeError, match='cannot be recomputed'):
            await service.refresh()
        if not config:
            with pytest.raises(RuntimeError, match='not installed'):
                service.replace(table)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_native_metadata_misses_are_fresh_but_selected_absence_is_cached(tmp_path):
    table, parent = probe.fixture(tmp_path, 'active')
    ctx = Context(); service = PluginPackages(ctx)
    assert service.packageOf('appeared', parent) is None
    destination = Path(table['profileDir']) / 'node_modules/appeared'
    probe.pkg(destination, 'appeared')
    assert service.packageOf('appeared', parent)['name'] == 'appeared'
    manifest = destination / 'package.json'; manifest.write_text('{', encoding='utf-8')
    assert service.packageOf('appeared', parent)['name'] == 'appeared'
    fresh = PluginPackages(Context())
    with pytest.raises(ValueError):
        fresh.packageOf('appeared', parent)
    await fresh.ctx.fiber.dispose(); await ctx.fiber.dispose()


def test_removed_link_history_relocates_external_imports_across_multiple_moves(tmp_path):
    table, _ = probe.fixture(tmp_path, 'active')
    old, middle, new = [tmp_path / name for name in ('old', 'middle', 'new')]
    for directory in (old, middle, new):
        directory.mkdir(); (directory / 'index.py').write_text('value = 1', encoding='utf-8')
    table['linkedRoots'] = [dict(name='linked', realPath=str(old))]
    router = ResolutionRouter(table)
    removed = copy.deepcopy(table); removed['linkedRoots'] = []; router.replace(removed)
    moved = copy.deepcopy(table); moved['linkedRoots'][0]['realPath'] = str(middle); router.replace(moved)
    moved = copy.deepcopy(moved); moved['linkedRoots'][0]['realPath'] = str(new); router.replace(moved)
    assert router.relocate(str(old / 'index.py')) == str(new / 'index.py')
    assert router.relocate(str(old / 'index.py'), str(old / 'caller.py')) == str(old / 'index.py')
    assert router.relocate(str(old / 'missing.py')) == str(old / 'missing.py')
    # A directory that becomes active again must lose stale redirects.
    router.replace(table)
    assert router.relocate(str(old / 'index.py')) == str(old / 'index.py')


def test_rejected_successor_does_not_relocate_link_history(tmp_path):
    table, _ = probe.fixture(tmp_path, 'active')
    old, new = tmp_path / 'old', tmp_path / 'new'
    for directory in (old, new):
        directory.mkdir(); (directory / 'index.py').write_text('', encoding='utf-8')
    table['linkedRoots'] = [dict(name='linked', realPath=str(old))]
    router = ResolutionRouter(table); changed = copy.deepcopy(table)
    changed['linkedRoots'][0]['realPath'] = str(new)
    changed['entries'][0]['version'] = '2.0.0'
    with pytest.raises(ResolutionRestartRequired): router.replace(changed)
    assert router.resolution is table
    assert router.relocate(str(old / 'index.py')) == str(old / 'index.py')
