import asyncio
import copy
import json
from pathlib import Path
import threading

import pytest

from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot.python_plugin_snapshot import restore_retained_package
from test_python_plugin_distribution import profile, close, boot, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start
from test_rc022_python_package_tarball import sri
from test_python_plugin_dependencies import project
from dsh.boot import python_plugin_dependencies as dependencies


def next_version(state, activation_error=False):
    metadata = copy.deepcopy(state['metadata'])
    metadata['version'] = '0.2.0'
    state['metadata'], state['index_version'] = metadata, '0.2.0'
    state['files']['python/echo/formatting.py'] = b'def format_echo(text):\n    return "Updated: " + text\n'
    if activation_error:
        code = state['files']['python/echo/plugin.py'].decode('utf-8')
        state['files']['python/echo/plugin.py'] = code.replace('    def apply(self, ctx, config):', '    def apply(self, ctx, config):\n        raise RuntimeError("new bundle cannot activate")').encode('utf-8')
    state['pack'](metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'disabled', 'download-fails', 'activation-error', 'cancel', 'restore-fails'])
async def test_actual_native_update_removal_install_and_owned_offline_restoration(profile, registry_package, mode, monkeypatch):
    home, directory = profile
    state = registry_package
    host = await start(home, state)
    ctx = host['ctx']
    recovery = None
    try:
        initial = await ctx.pluginManager.installBundle(PACKAGE, dict(enabled=mode != 'disabled'))
        assert initial['application'] == 'applied', initial
        previous = json.loads((directory / 'package.json').read_text(encoding='utf-8'))['dsh']['pythonPlugins'][PACKAGE]
        next_version(state, mode == 'activation-error')
        if mode in ('download-fails', 'restore-fails'):
            state['integrity'] = sri(b'wrong archive')
        if mode == 'restore-fails':
            actual = ctx.profilePackages._install
            async def reject_restore(candidate, result, options, snapshot=None):
                if snapshot is not None:
                    raise RuntimeError('injected snapshot restoration failure')
                return await actual(candidate, result, options, snapshot)
            monkeypatch.setattr(ctx.profilePackages, '_install', reject_restore)
        if mode == 'cancel':
            state['pause'], state['entered'] = threading.Event(), threading.Event()
        update = ctx.pluginManager.updateBundle(PACKAGE, '0.2.0', dict(requestId='update'))
        if mode == 'cancel':
            for _ in range(900):
                if state['entered'].is_set():
                    break
                await asyncio.sleep(.02)
            assert state['entered'].is_set()
            assert await asyncio.wait_for(ctx.pluginManager.cancelInstall('update'), 3) == dict(status='cancelled')
        result = await update
        assert result['from'] == '0.1.0' and result['to'] == '0.2.0' and result['step'] == 'install', result
        if mode in ('success', 'disabled'):
            assert result['result']['application'] == 'applied' and 'restore' not in result, result
            if mode == 'success':
                assert await echo(ctx) == 'Updated: hello'
            else:
                assert ctx.tools.get('python_echo') is None
                row = next(row for row in await ctx.pluginManager.listBundles() if row['name'] == PACKAGE)
                assert not row['enabled'] and row['source'] == PACKAGE + '@0.2.0'
        elif mode == 'restore-fails':
            assert result['restore']['application'] == 'failed', result
            recovery = result['recovery']['path']
            assert (Path(recovery) / 'package').is_dir() and (Path(recovery) / 'recovery.json').is_file()
            assert ctx.tools.get('python_echo') is None
        else:
            assert result['result']['application'] == ('cancelled' if mode == 'cancel' else 'failed'), result
            assert result['restore']['application'] == 'applied', result
            assert await echo(ctx) == 'Python echo: hello'
            restored = json.loads((directory / 'package.json').read_text(encoding='utf-8'))['dsh']['pythonPlugins'][PACKAGE]
            assert restored == previous
        assert not ctx.profilePackages.updates and not ctx.profilePackages.operations
        assert not (directory / '.dsh-python-downloads').exists()
        if mode != 'restore-fails':
            assert not (directory / '.dsh-python-updates').exists()
            assert (await ctx.pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
    finally:
        if 'pause' in state:
            state['pause'].set()
        await close(host)
    if recovery is not None:
        calls = list(state['requests'])
        assert restore_retained_package(str(directory), recovery, INSTALL_ANCHOR, enabled=True) == PACKAGE
        assert state['requests'] == calls and not Path(recovery).exists()
        restored_host = await boot(home)
        try:
            assert await echo(restored_host['ctx']) == 'Python echo: hello'
        finally:
            await close(restored_host)


def pack_project(state, source):
    metadata = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    state['metadata'], state['index_version'] = metadata, metadata['version']
    state['files'] = {name: (source / name).read_bytes() for name in metadata['dsh']['release']['files']}
    state['pack'](metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize('activation_error', [False, True])
async def test_native_update_replaces_library_imports_and_restores_old_graph(profile, registry_package, tmp_path, activation_error):
    home, directory = profile
    state = registry_package
    pack_project(state, project(tmp_path, version='0.1.0'))
    host = await start(home, state)
    old_paths, new_paths = [], []
    try:
        initial = await host['ctx'].pluginManager.installBundle(PACKAGE)
        assert initial['application'] == 'applied', initial
        assert await echo(host['ctx'], 'old') == 'locked-sub:old:1'
        old_paths = [row['temporary'].name for row in dependencies._POOL.values()]
        source = project(tmp_path, version='0.2.0', library_version='2.0.0', text='upgraded')
        pack_project(state, source)
        if activation_error:
            code = state['files']['python/echo/plugin.py'].decode('utf-8')
            state['files']['python/echo/plugin.py'] = code.replace('    def apply(self, ctx, config):', '    def apply(self, ctx, config):\n        raise RuntimeError("new library generation cannot activate")').encode('utf-8')
            state['pack'](state['metadata'])
        result = await host['ctx'].pluginManager.updateBundle(PACKAGE, '0.2.0')
        if activation_error:
            assert result['result']['application'] == 'failed' and result['restore']['application'] == 'applied', result
            assert await echo(host['ctx'], 'restored') == 'locked-sub:restored:1'
            assert dependencies._POOL['test-helper']['version'] == '1.0.0'
        else:
            assert result['result']['application'] == 'applied', result
            assert await echo(host['ctx'], 'new') == 'upgraded-sub:new:1'
            assert dependencies._POOL['test-helper']['version'] == '2.0.0'
        assert not any(Path(path).exists() for path in old_paths)
        new_paths = [row['temporary'].name for row in dependencies._POOL.values()]
        assert (await host['ctx'].pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
        assert not dependencies._POOL and not dependencies._PACKAGES
        assert not any(Path(path).exists() for path in new_paths)
        assert not (directory / '.dsh-python-updates').exists()
    finally:
        await close(host)
