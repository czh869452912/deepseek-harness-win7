import asyncio
import json
from pathlib import Path
import threading

import pytest

from dsh.boot.plugin_manager_current import CurrentPluginManager
from dsh.boot.profile_boot import run_profile
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package_backend import PythonPackageBackend
from dsh.cordis.hmr import ConfigWatcherService
from dsh.cordis.timer import TimerService
from test_python_plugin_distribution import profile, close, echo, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_python_plugin_dependencies import project
from dsh.boot import python_plugin_dependencies as dependencies


async def start(home, state, live=True):
    host = await run_profile(dict(profile='python-test', dshHome=str(home), args=[], waitForExit=False))
    ctx = host['ctx']
    certificate = Path(__file__).parent / 'fixtures/tls/localhost-cert.pem'
    try:
        await ctx.plugin(PythonPackageBackend, dict(env=dict(state['env'], PATH='', SSL_CERT_FILE=str(certificate.resolve()))))
        await ctx.plugin(CurrentPluginManager, dict(registry=state['url'], fallbackRegistries=[], lockWaitMs=0, idleTimeoutMs=10000))
        if live:
            await ctx.plugin(TimerService)
            await ctx.plugin(ConfigWatcherService, dict(root=[], ignored=[], debounce=0))
            await ctx.hmr.runExclusive(lambda: None)
        return host
    except BaseException:
        await close(host)
        raise


@pytest.mark.asyncio
async def test_actual_native_manager_install_execute_unload_remove(profile, registry_package):
    home, directory = profile
    host = await start(home, registry_package)
    ctx = host['ctx']
    try:
        logs = []
        ctx.on('plugin-manager/install-log', logs.append)
        result = await ctx.pluginManager.installBundle(PACKAGE, dict(requestId='real'))
        assert result['application'] == 'applied', result
        assert result['changed'] and result['bundle'] == PACKAGE and result['packageResult']['nativeCommitted']
        assert await echo(ctx) == 'Python echo: hello'
        assert any('Prepared ' + PACKAGE in row['text'] for row in logs)
        assert not (directory / '.dsh-python-downloads').exists()
        assert not list(directory.rglob('run.json'))
        before = (directory / 'package.json').read_bytes()
        direct = await ctx.profilePackages.run(dict(dir=str(directory)), ['remove', PACKAGE], {})
        assert direct['exitCode'] == 1 and (directory / 'package.json').read_bytes() == before
        assert await echo(ctx) == 'Python echo: hello'
        result = await ctx.pluginManager.removeBundle(PACKAGE)
        assert result['application'] == 'applied', result
        assert result['changed'] and not (directory / 'node_modules' / PACKAGE).exists()
        assert ctx.tools.get('python_echo') is None
        assert not ctx.pythonProfileLease.exclusive
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_disabled_install_then_enable_and_remove(profile, registry_package):
    home, directory = profile
    host = await start(home, registry_package)
    ctx = host['ctx']
    try:
        result = await ctx.pluginManager.installBundle(PACKAGE, dict(enabled=False))
        assert result['application'] == 'applied', result
        assert ctx.tools.get('python_echo') is None
        row = next(row for row in await ctx.pluginManager.listBundles() if row['name'] == PACKAGE)
        assert row['installed'] is True and not row['enabled'] and row['source'] == PACKAGE + '@0.1.0'
        repeat = await ctx.pluginManager.installBundle(PACKAGE)
        assert repeat['error']['code'] == 'already-installed'
        enabled = await ctx.pluginManager.setBundleEnabled(PACKAGE, True)
        assert enabled['application'] == 'applied', enabled
        assert await echo(ctx) == 'Python echo: hello'
        assert (await ctx.pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_other_host_refuses_before_package_commit(profile, registry_package):
    home, directory = profile
    host = await start(home, registry_package)
    before = (directory / 'package.json').read_bytes()
    try:
        with ProfileLease(str(directory)) as other:
            result = await host['ctx'].pluginManager.installBundle(PACKAGE)
            assert result['application'] == 'failed', result
            assert not result['changed'] and not (directory / 'node_modules' / PACKAGE).exists()
            assert other.stream is not None and not other.exclusive
        assert (directory / 'package.json').read_bytes() == before
        assert not (directory / '.dsh-python-downloads').exists()
        assert not host['ctx'].pythonProfileLease.exclusive
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_real_download_cancellation_drains_before_reporting(profile, registry_package):
    home, directory = profile
    state = registry_package
    host = await start(home, state)
    state['pause'], state['entered'] = threading.Event(), threading.Event()
    before = (directory / 'package.json').read_bytes()
    try:
        install = host['ctx'].pluginManager.installBundle(PACKAGE, dict(requestId='cancel'))
        for _ in range(600):
            if state['entered'].is_set():
                break
            await asyncio.sleep(.02)
        assert state['entered'].is_set()
        assert await asyncio.wait_for(host['ctx'].pluginManager.cancelInstall('cancel'), 3) == dict(status='cancelled')
        result = await install
        assert result['application'] == 'cancelled' and not result['changed'], result
        assert (directory / 'package.json').read_bytes() == before
        assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
        assert not (directory / 'node_modules' / PACKAGE).exists()
    finally:
        state['pause'].set()
        await close(host)


@pytest.mark.asyncio
async def test_commit_phase_refuses_late_cancellation(profile, registry_package):
    home, directory = profile
    host = await start(home, registry_package)
    cancellations = []
    phases = []
    def changed(event):
        phases.append(event['phase'])
        if event['phase'] == 'applying':
            cancellations.append(host['ctx'].pluginManager.cancelInstall('late'))
    host['ctx'].on('plugin-manager/install-state', changed)
    try:
        result = await host['ctx'].pluginManager.installBundle(PACKAGE, dict(requestId='late'))
        assert result['application'] == 'applied', result
        assert phases.count('applying') == 1
        assert [await item for item in cancellations] == [dict(status='too-late')]
        assert await echo(host['ctx']) == 'Python echo: hello'
        assert (await host['ctx'].pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
    finally:
        await close(host)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['abi', 'incompatible', 'expected'])
async def test_precommit_refusals_leave_profile_unchanged(profile, registry_package, failure):
    home, directory = profile
    state = registry_package
    if failure == 'abi':
        state['metadata']['dsh'].pop('python')
    if failure == 'incompatible':
        state['metadata']['engines'] = dict(dsh='>=99.0.0')
    host = await start(home, state)
    before = (directory / 'package.json').read_bytes()
    try:
        options = dict(expected=dict(name=PACKAGE, version='9.0.0')) if failure == 'expected' else {}
        result = await host['ctx'].pluginManager.installBundle(PACKAGE, options)
        assert result['application'] == 'failed' and not result['changed'], result
        if failure == 'incompatible':
            assert result['error']['code'] == 'incompatible-version', result
            assert result['error']['incompatible'][0]['name'] == PACKAGE
        if failure == 'expected':
            assert result['error']['code'] == 'unexpected-package', result
        assert (directory / 'package.json').read_bytes() == before
        assert not (directory / '.dsh-python-downloads').exists()
        assert not (directory / 'node_modules' / PACKAGE).exists()
    finally:
        await close(host)


@pytest.mark.asyncio
async def test_backend_unload_owns_and_drains_its_download(profile, registry_package):
    home, directory = profile
    state = registry_package
    host = await start(home, state)
    backend = host['ctx'].profilePackages
    state['pause'], state['entered'] = threading.Event(), threading.Event()
    before = (directory / 'package.json').read_bytes()
    try:
        install = host['ctx'].pluginManager.installBundle(PACKAGE)
        for _ in range(600):
            if state['entered'].is_set():
                break
            await asyncio.sleep(.02)
        assert state['entered'].is_set()
        await asyncio.wait_for(backend.ctx.fiber.dispose(), 3)
        result = await install
        assert result['application'] == 'failed' and not result['changed'], result
        assert backend.abort.signal.aborted and not backend.operations
        assert host['ctx'].get('profilePackages') is None
        assert (directory / 'package.json').read_bytes() == before
        assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
    finally:
        state['pause'].set()
        await close(host)


@pytest.mark.asyncio
async def test_real_manager_native_locked_libraries_live_until_last_unload(profile, registry_package, tmp_path):
    home, directory = profile
    state = registry_package
    source = project(tmp_path, version='0.1.0')
    metadata = json.loads((source / 'package.json').read_text(encoding='utf-8'))
    state['metadata'] = metadata
    state['files'] = {name: (source / name).read_bytes() for name in metadata['dsh']['release']['files']}
    state['pack'](metadata)
    host = await start(home, state)
    paths = []
    try:
        result = await host['ctx'].pluginManager.installBundle(PACKAGE)
        assert result['application'] == 'applied', result
        assert await echo(host['ctx'], 'dynamic') == 'locked-sub:dynamic:1'
        paths = [row['temporary'].name for row in dependencies._POOL.values()]
        assert len(paths) == 2 and all(Path(path).is_dir() for path in paths)
        result = await host['ctx'].pluginManager.removeBundle(PACKAGE)
        assert result['application'] == 'applied', result
        assert not dependencies._POOL and not dependencies._PACKAGES
        assert not any(Path(path).exists() for path in paths)
    finally:
        await close(host)
